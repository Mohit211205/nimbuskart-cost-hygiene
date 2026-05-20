# Design Note — Hardening, Scaling, and Productionising the Cost Janitor

## 1. Multi-Cloud Reality

NimbusKart plans to add GCP next quarter. The current janitor couples scan logic directly to `boto3`
calls. Adding a second cloud provider naively would require forking all four scan functions.

**Proposed module boundaries:**

```
janitor/
├── core/
│   ├── models.py        # Finding dataclass, shared enums — no cloud SDK imports
│   └── report.py        # build_report(), build_markdown() — operates only on Finding objects
├── providers/
│   ├── base.py          # Abstract CloudProvider with scan() -> list[Finding]
│   ├── aws.py           # AWSProvider: implements scan() using boto3
│   ├── gcp.py           # GCPProvider: implements scan() using google-cloud-compute
│   └── azure.py         # AzureProvider: implements scan() using azure-mgmt-compute
└── janitor.py           # CLI: instantiates the requested provider(s), calls scan(), calls report
```

The `base.py` abstract class would define four abstract methods matching the four orphan patterns:

```python
class CloudProvider(ABC):
    @abstractmethod
    def list_unattached_volumes(self) -> list[Finding]: ...
    @abstractmethod
    def list_long_stopped_instances(self, threshold_days: int) -> list[Finding]: ...
    @abstractmethod
    def list_unused_public_ips(self) -> list[Finding]: ...
    @abstractmethod
    def list_untagged_resources(self) -> list[Finding]: ...
```

Adding GCP means writing `GCPProvider` — the CLI, deduplication, and report logic are untouched.
The CLI accepts `--provider aws,gcp` and aggregates findings from both before generating the report.

---

## 2. Permissions

### --dry-run (read-only) IAM policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostJanitorReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVolumes",
        "ec2:DescribeInstances",
        "ec2:DescribeAddresses",
        "ec2:DescribeTags",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

### --delete additions (beyond read-only)

```
ec2:DeleteVolume       — restricted to volumes tagged ManagedBy=terraform
ec2:TerminateInstances — restricted to instances tagged ManagedBy=terraform
ec2:ReleaseAddress     — no resource-level condition available; scope by account
```

In practice, delete permissions should be attached to a separate IAM role assumed only when
`--delete` is passed explicitly, so the daily read-only run cannot accidentally destroy anything.

---

## 3. Safety Net — Two Failure Modes

### Failure Mode 1: Deleting a volume mid-migration

**Scenario:** NimbusKart migrates a database to a larger instance type. The old volume is detached
from the source instance, then re-attached to the new one a few minutes later. If the Janitor runs
during that window, it sees an `available` volume and — if `--delete` is active — removes it
permanently before the migration completes, causing data loss and a production outage.

**Guardrails:**
- Enforce a minimum age threshold for unattached volumes (e.g. skip volumes created or last
  detached within the past 2 hours).
- Query `describe_volumes` for `AttachTime` on the most recent attachment and use that as the
  clock, not `CreateTime`.
- Tag volumes that are part of an active migration with `Protected=true` via the runbook.

### Failure Mode 2: Terminating a scheduled-wake instance

**Scenario:** NimbusKart runs a nightly batch job on a t3.large instance. The instance is stopped
between runs and started automatically by an EventBridge schedule. If the Janitor runs between
starts and the stop age exceeds the threshold, it terminates the instance and its root volume,
breaking the batch pipeline silently.

**Guardrails:**
- Before terminating any instance, check whether an EventBridge rule or Auto Scaling group
  references its AMI or launch template (`ec2:DescribeScheduledInstanceAvailability`,
  `events:ListTargetsByRule`). Flag these as `safe_to_auto_delete: false`.
- Implement a two-phase approach: on the first scan, tag the instance
  `CostJanitor_PendingDeletion=<ISO-timestamp>`. Only delete on a subsequent scan if the tag is
  still present and the grace period (e.g. 7 days) has elapsed. This gives the team a window to
  intervene.

---

## 4. Observability

Publish these metrics to **CloudWatch** (namespace `CostJanitor`) from inside `janitor.py` using
`cloudwatch:PutMetricData`. The FinOps team subscribes a CloudWatch alarm to each.

| Metric | Source | Alert threshold |
|--------|--------|-----------------|
| `OrphansFound` (count) | `report["summary"]["total_orphans"]` | > 20 in a single scan — sudden spike indicates a runaway provisioning script |
| `EstimatedWasteUSD` (gauge) | `report["summary"]["estimated_monthly_waste_usd"]` | > 300 USD/month — absolute cost ceiling the FinOps team has agreed |
| `ScanDurationSeconds` (timer) | wall-clock time around `main()` | > 300 s — signals API throttling or a hung paginator |
| `DeleteErrors` (count) | exception counter inside `delete_findings()` | > 0 — any failed deletion needs human review |
| `LastSuccessfulRunAge` (gauge, seconds since epoch) | timestamp written to SSM Parameter Store after a clean run | > 90 000 s (≈25 h) — the daily job missed a run |

---

## 5. What I Did Not Build

The following items were consciously descoped to stay within the time budget:

- **Multi-region scanning.** The current script targets a single region passed via `--region`. A
  production implementation would iterate over all regions returned by `ec2:DescribeRegions` and
  aggregate findings. This was omitted because the assignment evaluates architecture thinking, not
  iteration length.
- **Additional resource types.** RDS snapshots, unused NAT Gateways, idle load balancers, and
  unattached Elastic Network Interfaces are all meaningful waste sources at NimbusKart's scale but
  were not in the spec's required four patterns.
- **Notification delivery.** The report is written to disk and uploaded as a CI artifact. A
  production version would also push a summary to a Slack channel or SNS topic. Omitted because
  the required PR-comment workflow already covers the CI notification path.
- **State persistence.** The Janitor has no memory between runs, so it cannot distinguish a new
  orphan from one that has been reviewed and accepted. A simple DynamoDB or S3-backed state file
  would allow suppressing known-safe findings; omitted to avoid scope creep.
- **Cost accuracy.** Prices are hard-coded constants. A production tool would call the AWS Price
  List API or use the Cost Explorer API to get region- and reservation-adjusted figures.
