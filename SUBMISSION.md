# Submission — DevOps Engineer Assignment

**Candidate name:**
**Email:**
**Date submitted:**
**Hours spent (approximate):**

## Deliverables checklist

- [x] Part A: Terraform code under /terraform applies cleanly on LocalStack
- [x] Part A: `terraform validate` and `terraform fmt -check` both pass
- [x] Part B: Janitor script runs in --dry-run mode and produces report.json
- [x] Part B: GitHub Actions workflow runs green on a fresh PR
- [x] Part B: --delete mode respects Protected=true tag
- [x] Part C: DESIGN.md is present and within 2 pages
- [ ] Walkthrough video link below is accessible (unlisted is fine)

## Walkthrough video

Link (Loom / YouTube unlisted / Google Drive):
Length: max 5 minutes

## Sample report

Path to a sample report.json produced by your script: `samples/report.example.json`

## Known limitations

- EIP `age_days` is always reported as 0 because `describe_addresses` does not return an
  allocation timestamp. CloudTrail could supply this in a production implementation.
- Stopped-instance age detection relies on parsing the `StateTransitionReason` string, which
  LocalStack leaves empty. The fallback treats empty reason as 999 days, so all stopped instances
  are flagged in LocalStack. Real AWS instances populate this field correctly.
- Only `us-east-1` is scanned per run. Multi-region support is described in README Trade-offs.
- Cost estimates use static per-unit prices (see `janitor/constants.py`). They do not reflect
  reserved instance discounts or savings plans.

## AI usage disclosure

See the `## AI Usage Disclosure` section in README.md for full details.
