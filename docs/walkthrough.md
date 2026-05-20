# Walkthrough Video

## Link

<!-- Replace the placeholder below with your actual Loom or YouTube unlisted link -->
**Video URL:** _to be added_

**Length:** _to be added (max 5 minutes)_

---

## What the video covers

The walkthrough demonstrates the following four items as required by the assignment brief:

1. **Starting LocalStack and applying Terraform live** — shows `docker run` starting LocalStack,
   followed by `tflocal init` and `tflocal apply`, ending with the output values (VPC ID, subnet
   IDs, bucket name, orphan volume ID).

2. **Running the Cost Janitor and walking through a finding** — runs `python janitor.py --dry-run
   --endpoint-url http://localhost:4566` and opens `reports/report.json`, highlighting the
   unattached EBS volume finding created by Terraform in Part A.

3. **A design decision I am proud of** — the `parse_stop_age()` function that handles the
   `StateTransitionReason` freeform string safely, including the LocalStack fallback, and the
   reasoning behind the `safe_to_auto_delete=false` rule for tagging findings.

4. **One thing I would change** — multi-region scanning: the current single-region design is the
   biggest gap between this prototype and a production tool, and I describe how the
   `ec2:DescribeRegions` loop would be added.

---

## Transcript

_Add a brief transcript or notes here after recording._
