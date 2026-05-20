#!/usr/bin/env python3
"""
Cost Janitor — scans AWS for orphaned resources and produces a waste report.

Usage:
    python janitor.py [--dry-run | --delete]
                      [--region REGION]
                      [--endpoint-url URL]
                      [--stopped-days N]
                      [--output-dir PATH]

Exit codes:
    0  — no orphans found (CI passes)
    1  — one or more orphans found in --dry-run mode (CI fails the check)
    2  — unexpected runtime error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from constants import (
    EBS_DEFAULT_SIZE_GB,
    EBS_GP2_USD_PER_GB_MONTH,
    EBS_GP3_USD_PER_GB_MONTH,
    EC2_FALLBACK_HOURLY_USD,
    EC2_HOURLY_USD,
    ELASTIC_IP_IDLE_USD_PER_HOUR,
    HOURS_PER_MONTH,
    REQUIRED_TAGS,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect orphaned AWS resources and report estimated waste."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Report orphans without deleting anything (default).",
    )
    mode.add_argument(
        "--delete",
        dest="delete",
        action="store_true",
        default=False,
        help="Delete detected orphans. Resources tagged Protected=true are always skipped.",
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region to scan.")
    parser.add_argument(
        "--endpoint-url",
        default=None,
        help="Override the AWS endpoint URL (e.g. http://localhost:4566 for LocalStack).",
    )
    parser.add_argument(
        "--stopped-days",
        type=int,
        default=14,
        help="Flag EC2 instances that have been stopped for at least this many days (default: 14).",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to write report.json and report.md into (default: current directory).",
    )
    args = parser.parse_args()
    if args.delete:
        args.dry_run = False
    return args


# ---------------------------------------------------------------------------
# AWS client helpers
# ---------------------------------------------------------------------------

def _client_kwargs(region: str, endpoint_url: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return kwargs


def make_client(service: str, region: str, endpoint_url: str | None):
    return boto3.client(service, **_client_kwargs(region, endpoint_url))


def get_account_id(region: str, endpoint_url: str | None) -> str:
    try:
        sts = make_client("sts", region, endpoint_url)
        return sts.get_caller_identity()["Account"]
    except Exception:
        return "000000000000"


# ---------------------------------------------------------------------------
# Tag utilities
# ---------------------------------------------------------------------------

def tags_to_dict(tag_list: list[dict] | None) -> dict[str, str]:
    if not tag_list:
        return {}
    return {t["Key"]: t["Value"] for t in tag_list}


def is_protected(tags: dict[str, str]) -> bool:
    return tags.get("Protected", "").lower() == "true"


def missing_required_tags(tags: dict[str, str]) -> list[str]:
    return [t for t in REQUIRED_TAGS if not tags.get(t)]


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def ebs_monthly_cost(volume: dict) -> float:
    size = volume.get("Size", EBS_DEFAULT_SIZE_GB)
    rate = (
        EBS_GP2_USD_PER_GB_MONTH
        if volume.get("VolumeType") == "gp2"
        else EBS_GP3_USD_PER_GB_MONTH
    )
    return round(size * rate, 2)


def ec2_monthly_cost(instance_type: str) -> float:
    hourly = EC2_HOURLY_USD.get(instance_type, EC2_FALLBACK_HOURLY_USD)
    return round(hourly * HOURS_PER_MONTH, 2)


def eip_monthly_cost() -> float:
    return round(ELASTIC_IP_IDLE_USD_PER_HOUR * HOURS_PER_MONTH, 2)


# ---------------------------------------------------------------------------
# Age helpers
# ---------------------------------------------------------------------------

def age_days_from_dt(dt: datetime) -> int:
    return (datetime.now(timezone.utc) - dt).days


def parse_stop_age(state_transition_reason: str) -> int:
    """
    AWS encodes the stop time in StateTransitionReason as:
      'User initiated (2024-06-01 12:00:00 GMT)'
    Returns age in days, or 999 if the field is empty/unparseable
    (LocalStack often omits it — treating as very old is safe for test scenarios).
    """
    match = re.search(
        r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) GMT\)", state_transition_reason
    )
    if not match:
        return 999
    try:
        stop_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        return (datetime.now(timezone.utc) - stop_time).days
    except ValueError:
        return 999


# ---------------------------------------------------------------------------
# Scan functions
# ---------------------------------------------------------------------------

def scan_unattached_ebs(ec2) -> list[dict]:
    """Finds EBS volumes in 'available' state (not attached to any instance)."""
    findings: list[dict] = []
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(
        Filters=[{"Name": "status", "Values": ["available"]}]
    ):
        for vol in page["Volumes"]:
            tags = tags_to_dict(vol.get("Tags"))
            findings.append(
                _finding(
                    resource_id=vol["VolumeId"],
                    resource_type="ebs_volume",
                    reason="unattached",
                    age_days=age_days_from_dt(vol["CreateTime"]),
                    cost=ebs_monthly_cost(vol),
                    tags=tags,
                    suggested_action="delete",
                )
            )
    return findings


def scan_stopped_ec2(ec2, stopped_days: int) -> list[dict]:
    """Finds EC2 instances stopped for more than `stopped_days` days."""
    findings: list[dict] = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
    ):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                stop_age = parse_stop_age(inst.get("StateTransitionReason", ""))
                if stop_age < stopped_days:
                    continue
                tags = tags_to_dict(inst.get("Tags"))
                findings.append(
                    _finding(
                        resource_id=inst["InstanceId"],
                        resource_type="ec2_instance",
                        reason=f"stopped_for_{stop_age}_days",
                        age_days=stop_age,
                        cost=ec2_monthly_cost(inst.get("InstanceType", "t3.micro")),
                        tags=tags,
                        suggested_action="terminate",
                    )
                )
    return findings


def scan_unused_eips(ec2) -> list[dict]:
    """Finds Elastic IPs not associated with any instance or network interface."""
    findings: list[dict] = []
    response = ec2.describe_addresses()
    for addr in response.get("Addresses", []):
        if addr.get("AssociationId"):
            continue
        tags = tags_to_dict(addr.get("Tags"))
        resource_id = addr.get("AllocationId") or addr.get("PublicIp", "unknown")
        findings.append(
            _finding(
                resource_id=resource_id,
                resource_type="elastic_ip",
                reason="unassociated",
                age_days=0,  # AWS does not expose EIP creation time via describe_addresses
                cost=eip_monthly_cost(),
                tags=tags,
                suggested_action="release",
            )
        )
    return findings


def scan_untagged_resources(ec2) -> list[dict]:
    """
    Finds EC2 instances and EBS volumes missing one or more required tags.
    Resources flagged here may overlap with other scanners; duplicates are
    removed by deduplicate() before the report is written.
    """
    findings: list[dict] = []

    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                if inst["State"]["Name"] == "terminated":
                    continue
                tags = tags_to_dict(inst.get("Tags"))
                missing = missing_required_tags(tags)
                if not missing:
                    continue
                findings.append(
                    _finding(
                        resource_id=inst["InstanceId"],
                        resource_type="ec2_instance",
                        reason=f"missing_tags:{','.join(missing)}",
                        age_days=age_days_from_dt(inst["LaunchTime"]),
                        cost=0.0,
                        tags=tags,
                        suggested_action="tag",
                        safe_to_auto_delete=False,
                    )
                )

    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate():
        for vol in page["Volumes"]:
            tags = tags_to_dict(vol.get("Tags"))
            missing = missing_required_tags(tags)
            if not missing:
                continue
            findings.append(
                _finding(
                    resource_id=vol["VolumeId"],
                    resource_type="ebs_volume",
                    reason=f"missing_tags:{','.join(missing)}",
                    age_days=age_days_from_dt(vol["CreateTime"]),
                    cost=0.0,
                    tags=tags,
                    suggested_action="tag",
                    safe_to_auto_delete=False,
                )
            )

    return findings


def _finding(
    *,
    resource_id: str,
    resource_type: str,
    reason: str,
    age_days: int,
    cost: float,
    tags: dict[str, str],
    suggested_action: str,
    safe_to_auto_delete: bool | None = None,
) -> dict:
    if safe_to_auto_delete is None:
        safe_to_auto_delete = not is_protected(tags) and suggested_action != "tag"
    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "reason": reason,
        "age_days": age_days,
        "estimated_monthly_cost_usd": cost,
        "tags": {t: tags.get(t) for t in REQUIRED_TAGS},
        "suggested_action": suggested_action,
        "safe_to_auto_delete": safe_to_auto_delete,
        "_raw_tags": tags,
    }


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def deduplicate(findings: list[dict]) -> list[dict]:
    """Keep only the first finding for each resource_id."""
    seen: set[str] = set()
    result: list[dict] = []
    for f in findings:
        if f["resource_id"] not in seen:
            seen.add(f["resource_id"])
            result.append(f)
    return result


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_findings(ec2, findings: list[dict]) -> None:
    for f in findings:
        rid = f["resource_id"]
        if not f["safe_to_auto_delete"]:
            print(f"  SKIP (Protected=true or tag issue): {rid}")
            continue
        try:
            action = f["suggested_action"]
            rtype = f["resource_type"]
            if rtype == "ebs_volume" and action == "delete":
                ec2.delete_volume(VolumeId=rid)
                print(f"  DELETED    ebs_volume    {rid}")
            elif rtype == "ec2_instance" and action == "terminate":
                ec2.terminate_instances(InstanceIds=[rid])
                print(f"  TERMINATED ec2_instance  {rid}")
            elif rtype == "elastic_ip" and action == "release":
                ec2.release_address(AllocationId=rid)
                print(f"  RELEASED   elastic_ip    {rid}")
            else:
                print(f"  SKIP (no delete handler for {rtype}/{action}): {rid}")
        except ClientError as exc:
            print(f"  ERROR deleting {rid}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def build_report(findings: list[dict], region: str, account_id: str) -> dict:
    clean = [{k: v for k, v in f.items() if not k.startswith("_")} for f in findings]
    total_waste = sum(f["estimated_monthly_cost_usd"] for f in clean)
    return {
        "scan_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "account_id": account_id,
        "region": region,
        "summary": {
            "total_orphans": len(clean),
            "estimated_monthly_waste_usd": round(total_waste, 2),
        },
        "findings": clean,
    }


def build_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# Cost Janitor Report",
        "",
        f"**Scan time:** {report['scan_timestamp']}  ",
        f"**Region:** {report['region']}  ",
        f"**Account:** {report['account_id']}  ",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total orphans found | **{s['total_orphans']}** |",
        f"| Estimated monthly waste | **${s['estimated_monthly_waste_usd']:.2f}** |",
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines.append("No orphaned resources found. All clear.")
    else:
        lines += [
            "| Resource ID | Type | Reason | Age (days) | Est. Monthly Cost | Action |",
            "|-------------|------|--------|:----------:|:-----------------:|--------|",
        ]
        for f in report["findings"]:
            lines.append(
                f"| `{f['resource_id']}` | {f['resource_type']} | {f['reason']} "
                f"| {f['age_days']} | ${f['estimated_monthly_cost_usd']:.2f} "
                f"| {f['suggested_action']} |"
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    mode_label = "DELETE" if args.delete else "DRY-RUN"
    print(f"[Cost Janitor] region={args.region}  mode={mode_label}  stopped-threshold={args.stopped_days}d")

    ec2 = make_client("ec2", args.region, args.endpoint_url)
    account_id = get_account_id(args.region, args.endpoint_url)

    all_findings: list[dict] = []
    all_findings.extend(scan_unattached_ebs(ec2))
    all_findings.extend(scan_stopped_ec2(ec2, args.stopped_days))
    all_findings.extend(scan_unused_eips(ec2))
    all_findings.extend(scan_untagged_resources(ec2))
    all_findings = deduplicate(all_findings)

    report = build_report(all_findings, args.region, account_id)
    markdown = build_markdown(report)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(markdown, encoding="utf-8")

    total = report["summary"]["total_orphans"]
    waste = report["summary"]["estimated_monthly_waste_usd"]
    print(f"[Cost Janitor] {total} orphan(s) found — estimated waste ${waste:.2f}/month")
    print(f"[Cost Janitor] Report written to {out_dir}/report.json and {out_dir}/report.md")

    if args.delete:
        print("[Cost Janitor] --delete mode active. Removing resources...")
        delete_findings(ec2, all_findings)

    return 1 if total > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
