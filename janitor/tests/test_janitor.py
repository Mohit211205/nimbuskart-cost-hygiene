"""
Unit tests for the Cost Janitor.

Uses Moto to mock AWS services — no real credentials or LocalStack required.
Run from the repo root with:  pytest janitor/tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).parent.parent))

from janitor import (
    build_markdown,
    build_report,
    deduplicate,
    is_protected,
    missing_required_tags,
    scan_unattached_ebs,
    scan_stopped_ec2,
    scan_untagged_resources,
    scan_unused_eips,
)

REGION = "us-east-1"
AZ = f"{REGION}a"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ec2():
    return boto3.client("ec2", region_name=REGION)


# ---------------------------------------------------------------------------
# EBS volume scans
# ---------------------------------------------------------------------------

@mock_aws
def test_scan_unattached_ebs_detects_available_volume():
    ec2 = _ec2()
    ec2.create_volume(AvailabilityZone=AZ, Size=10, VolumeType="gp3")
    findings = scan_unattached_ebs(ec2)
    assert len(findings) == 1
    assert findings[0]["resource_type"] == "ebs_volume"
    assert findings[0]["reason"] == "unattached"
    assert findings[0]["suggested_action"] == "delete"


@mock_aws
def test_scan_unattached_ebs_cost_calculation():
    ec2 = _ec2()
    ec2.create_volume(AvailabilityZone=AZ, Size=20, VolumeType="gp3")
    findings = scan_unattached_ebs(ec2)
    # 20 GB * $0.08 = $1.60
    assert findings[0]["estimated_monthly_cost_usd"] == pytest.approx(1.60)


@mock_aws
def test_scan_unattached_ebs_ignores_in_use_volume():
    ec2 = _ec2()
    reservation = ec2.run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro"
    )
    instance_id = reservation["Instances"][0]["InstanceId"]
    vol = ec2.create_volume(AvailabilityZone=AZ, Size=8)
    ec2.attach_volume(VolumeId=vol["VolumeId"], InstanceId=instance_id, Device="/dev/sdf")
    findings = scan_unattached_ebs(ec2)
    assert not any(f["resource_id"] == vol["VolumeId"] for f in findings)


# ---------------------------------------------------------------------------
# Elastic IP scans
# ---------------------------------------------------------------------------

@mock_aws
def test_scan_unused_eips_detects_unassociated_address():
    ec2 = _ec2()
    ec2.allocate_address(Domain="vpc")
    findings = scan_unused_eips(ec2)
    assert len(findings) == 1
    assert findings[0]["resource_type"] == "elastic_ip"
    assert findings[0]["suggested_action"] == "release"


@mock_aws
def test_scan_unused_eips_ignores_associated_address():
    ec2 = _ec2()
    reservation = ec2.run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro"
    )
    instance_id = reservation["Instances"][0]["InstanceId"]
    alloc = ec2.allocate_address(Domain="vpc")
    ec2.associate_address(
        InstanceId=instance_id, AllocationId=alloc["AllocationId"]
    )
    findings = scan_unused_eips(ec2)
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Untagged resource scans
# ---------------------------------------------------------------------------

@mock_aws
def test_scan_untagged_flags_instance_missing_all_tags():
    ec2 = _ec2()
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")
    findings = scan_untagged_resources(ec2)
    instance_findings = [f for f in findings if f["resource_type"] == "ec2_instance"]
    assert len(instance_findings) >= 1
    assert "missing_tags" in instance_findings[0]["reason"]


@mock_aws
def test_scan_untagged_ignores_fully_tagged_instance():
    ec2 = _ec2()
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Project", "Value": "nimbuskart"},
                {"Key": "Environment", "Value": "staging"},
                {"Key": "Owner", "Value": "platform-team"},
                {"Key": "ManagedBy", "Value": "terraform"},
            ],
        }],
    )
    findings = scan_untagged_resources(ec2)
    instance_findings = [f for f in findings if f["resource_type"] == "ec2_instance"]
    assert len(instance_findings) == 0


# ---------------------------------------------------------------------------
# Protected tag
# ---------------------------------------------------------------------------

@mock_aws
def test_protected_tag_sets_safe_to_auto_delete_false():
    ec2 = _ec2()
    ec2.create_volume(
        AvailabilityZone=AZ,
        Size=10,
        VolumeType="gp3",
        TagSpecifications=[{
            "ResourceType": "volume",
            "Tags": [{"Key": "Protected", "Value": "true"}],
        }],
    )
    findings = scan_unattached_ebs(ec2)
    assert findings[0]["safe_to_auto_delete"] is False


# ---------------------------------------------------------------------------
# Tag utilities
# ---------------------------------------------------------------------------

def test_missing_required_tags_partial():
    assert set(missing_required_tags({"Project": "x"})) == {"Environment", "Owner"}


def test_missing_required_tags_none_missing():
    tags = {"Project": "x", "Environment": "y", "Owner": "z"}
    assert missing_required_tags(tags) == []


def test_is_protected_case_insensitive():
    assert is_protected({"Protected": "true"}) is True
    assert is_protected({"Protected": "True"}) is True
    assert is_protected({"Protected": "TRUE"}) is True
    assert is_protected({"Protected": "false"}) is False
    assert is_protected({}) is False


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_deduplicate_removes_duplicate_resource_ids():
    findings = [
        {"resource_id": "vol-abc", "resource_type": "ebs_volume", "reason": "unattached"},
        {"resource_id": "vol-abc", "resource_type": "ebs_volume", "reason": "missing_tags:Owner"},
    ]
    result = deduplicate(findings)
    assert len(result) == 1
    assert result[0]["reason"] == "unattached"


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

def test_build_report_structure():
    findings = [
        {
            "resource_id": "vol-test",
            "resource_type": "ebs_volume",
            "reason": "unattached",
            "age_days": 30,
            "estimated_monthly_cost_usd": 8.0,
            "tags": {"Project": None, "Environment": None, "Owner": None},
            "suggested_action": "delete",
            "safe_to_auto_delete": True,
        }
    ]
    report = build_report(findings, "us-east-1", "123456789012")
    assert report["summary"]["total_orphans"] == 1
    assert report["summary"]["estimated_monthly_waste_usd"] == 8.0
    assert "scan_timestamp" in report
    assert len(report["findings"]) == 1


def test_build_markdown_contains_table():
    findings = [
        {
            "resource_id": "vol-abc",
            "resource_type": "ebs_volume",
            "reason": "unattached",
            "age_days": 10,
            "estimated_monthly_cost_usd": 0.80,
            "tags": {"Project": None, "Environment": "staging", "Owner": None},
            "suggested_action": "delete",
            "safe_to_auto_delete": True,
        }
    ]
    report = build_report(findings, "us-east-1", "000000000000")
    md = build_markdown(report)
    assert "vol-abc" in md
    assert "unattached" in md
    assert "$0.80" in md
