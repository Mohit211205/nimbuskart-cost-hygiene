"""
Pricing constants used for monthly waste estimation.

All prices are for us-east-1 (N. Virginia) on-demand, retrieved May 2026.

Sources:
  EBS pricing  — https://aws.amazon.com/ebs/pricing/
  EC2 pricing  — https://aws.amazon.com/ec2/pricing/on-demand/
  EIP pricing  — https://aws.amazon.com/vpc/pricing/
"""

# EBS — per GB per month
EBS_GP3_USD_PER_GB_MONTH: float = 0.08
EBS_GP2_USD_PER_GB_MONTH: float = 0.10
EBS_DEFAULT_SIZE_GB: int = 8

# EC2 — hourly on-demand price per instance type
EC2_HOURLY_USD: dict[str, float] = {
    "t3.micro":   0.0104,
    "t3.small":   0.0208,
    "t3.medium":  0.0416,
    "t3.large":   0.0832,
    "t3.xlarge":  0.1664,
    "t3.2xlarge": 0.3328,
}
EC2_FALLBACK_HOURLY_USD: float = 0.05  # conservative default for unknown types

HOURS_PER_MONTH: int = 730

# Elastic IP — idle (unassociated) charge per hour
ELASTIC_IP_IDLE_USD_PER_HOUR: float = 0.005

# Tags every resource must carry
REQUIRED_TAGS: list[str] = ["Project", "Environment", "Owner"]
