# Cost Janitor Report

**Scan time:** 2026-05-20T10:00:00Z  
**Region:** us-east-1  
**Account:** 000000000000  

## Summary

| Metric | Value |
|--------|-------|
| Total orphans found | **3** |
| Estimated monthly waste | **$12.15** |

## Findings

| Resource ID | Type | Reason | Age (days) | Est. Monthly Cost | Action |
|-------------|------|--------|:----------:|:-----------------:|--------|
| `vol-0a1b2c3d4e5f67890` | ebs_volume | unattached | 21 | $0.80 | delete |
| `i-0fedcba9876543210` | ec2_instance | stopped_for_18_days | 18 | $7.59 | terminate |
| `eipalloc-0a1b2c3d4e5f67890` | elastic_ip | unassociated | 0 | $3.65 | release |
