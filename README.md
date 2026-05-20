# NimbusKart — Cloud Cost Hygiene Automation

## Overview

This repository implements a cloud cost-hygiene foundation for NimbusKart, a fictional e-commerce
startup whose AWS bill unexpectedly tripled over one quarter. It contains three deliverables that
work together: Terraform Infrastructure as Code that provisions NimbusKart's staging environment
against a local AWS emulator (LocalStack); a Python "Cost Janitor" that scans for orphaned
resources and produces a structured waste report; and a GitHub Actions pipeline that runs the
janitor on every pull request, uploads the report as a CI artifact, and comments on the PR if
orphans are found.

---

## How to Run Locally

Prerequisites: **Docker Desktop**, **Python 3.11+**, **Terraform 1.7+**, **Git**.

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/nimbuskart-cost-hygiene.git
cd nimbuskart-cost-hygiene

# 2. Start LocalStack (AWS emulator)
docker run --rm -d -p 4566:4566 --name localstack localstack/localstack

# 3. Install the tflocal wrapper
pip install terraform-local

# 4. Initialise and apply Terraform
cd terraform
tflocal init
tflocal apply -auto-approve
cd ..

# 5. Install Python dependencies
pip install -r janitor/requirements.txt

# 6. Run the Cost Janitor in dry-run mode (default)
python janitor/janitor.py \
  --endpoint-url http://localhost:4566 \
  --output-dir reports

# 7. Inspect the report
cat reports/report.json
cat reports/report.md

# 8. (Optional) Run with --delete to remove safe orphans
python janitor/janitor.py \
  --delete \
  --endpoint-url http://localhost:4566 \
  --output-dir reports

# 9. Run the unit test suite (uses Moto — no LocalStack required)
pytest janitor/tests/ -v
```

To tear down the LocalStack container when finished:

```bash
docker stop localstack
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        GitHub Repository                              │
│                                                                        │
│  ┌────────────────────┐     ┌─────────────────────────────────────┐  │
│  │   /terraform        │     │       GitHub Actions CI/CD          │  │
│  │                     │     │                                      │  │
│  │  modules/network/   │     │  1. Start LocalStack (service)      │  │
│  │  ├── main.tf        │     │  2. tflocal init && apply           │  │
│  │  ├── variables.tf   │     │  3. pytest janitor/tests/           │  │
│  │  └── outputs.tf     │     │  4. python janitor.py --dry-run     │  │
│  │                     │     │  5. Upload report artifacts          │  │
│  │  main.tf            │     │  6. Post PR comment if orphans found │  │
│  │  variables.tf       │     └─────────────────────────────────────┘  │
│  │  outputs.tf         │                                               │
│  └────────────────────┘                                               │
│                                                                        │
│  ┌────────────────────┐     ┌─────────────────────────────────────┐  │
│  │   /janitor          │     │   LocalStack (Docker)               │  │
│  │                     │     │                                      │  │
│  │  janitor.py  ───────┼────▶│   EC2  │  S3  │  IAM  │  STS       │  │
│  │  constants.py       │     │                                      │  │
│  │  tests/             │     │   Emulates AWS APIs on port 4566    │  │
│  └────────────────────┘     └─────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘

Cost Janitor scan flow:
  EC2 API ──► scan_unattached_ebs()     ─┐
  EC2 API ──► scan_stopped_ec2()        ─┤─► deduplicate() ──► build_report()
  EC2 API ──► scan_unused_eips()        ─┤                         │
  EC2 API ──► scan_untagged_resources() ─┘                    report.json
                                                               report.md
```

---

## Decisions & Deviations

- **SSH CIDR default changed from `0.0.0.0/0` to `10.0.0.0/8`.** Exposing port 22 to the entire
  internet is a critical security risk. The variable remains configurable; override it to a
  specific bastion or VPN CIDR before deploying to any real environment.

- **No `random_id` suffix on the S3 bucket name.** The spec does not require global uniqueness in
  a LocalStack context. Adding a random suffix would make the bucket name unpredictable and break
  the output value. If this were a real AWS deployment, a suffix or a pre-registered bucket name
  convention would be required.

- **`ami_id` defaults to a fixed string.** LocalStack does not validate AMI IDs, so a real AMI ID
  would be hard-coded and potentially stale. In a real deployment this variable would be populated
  by a data source (`aws_ami`) or a pipeline parameter.

- **Stopped-instance age falls back to 999 days when `StateTransitionReason` is empty.** LocalStack
  does not populate this field. In production this behaviour is correct: an instance with no stop
  timestamp is treated conservatively as very old.

- **`safe_to_auto_delete` is always `false` for tagging findings.** A missing tag is a hygiene
  issue, not a deletion signal. Auto-deleting a resource because it lacks a tag would be far more
  destructive than useful.

- **EIP `age_days` is reported as 0.** The `describe_addresses` API does not return the allocation
  timestamp. In production, CloudTrail event history could supply this; omitted to avoid
  additional API scope in the read-only policy.

---

## Trade-offs

Given one additional week, the following improvements would be the highest priority:

- **Multi-region iteration.** The current script targets a single region. Looping over
  `ec2:DescribeRegions` and parallelising the scans with `concurrent.futures` would take roughly
  half a day and substantially increase coverage.
- **State file for suppression.** Without persistent state the Janitor re-reports the same
  findings every day. A lightweight DynamoDB table or S3 JSON file to track `acknowledged` orphans
  would reduce noise dramatically.
- **Real-time pricing via AWS Price List API.** Hard-coded constants go stale. Calling the Price
  List API on start-up (with a 24-hour cache) would produce accurate cost estimates.
- **Terraform remote state.** Using an S3 backend with DynamoDB locking instead of local state
  is a prerequisite for any team use.
- **Provider abstraction for GCP.** The `base.py` interface described in `DESIGN.md` would be
  implemented and a GCP provider added using `google-cloud-compute`.

---

## AI Usage Disclosure

This project was built with the assistance of **Claude (Anthropic)** via Claude Code.

**What Claude was used for:**
- Generating the initial Terraform module structure and provider configuration for LocalStack.
- Drafting the boilerplate structure of `janitor.py` (argument parser, paginator loops, report
  builder functions).
- Writing the DESIGN.md section on IAM policy JSON — confirmed against AWS documentation.
- Suggesting the two-phase deletion guardrail (tag-then-delete) described in the safety net section.

**One thing Claude got wrong:**
Claude initially generated the GitHub Actions `services` health-check command as
`curl -s http://localhost:4566/_localstack/health | grep -q running`, which never matched because
the LocalStack health response format changed in recent versions. I diagnosed this by running the
container locally and inspecting the actual JSON response, then corrected it to check for the
`"ec2"` key instead.

**One section written without AI assistance:**
The `parse_stop_age()` function in `janitor.py` was written manually. The AWS SDK returns the stop
timestamp embedded in a freeform string (`StateTransitionReason`), and Claude's initial suggestion
used a different regex that failed on the exact format LocalStack produces. I read the boto3 docs,
tested the actual string format in a REPL, and wrote the regex and fallback logic myself.
