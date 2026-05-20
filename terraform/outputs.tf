output "vpc_id" {
  description = "ID of the NimbusKart staging VPC."
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "IDs of the two public subnets."
  value       = module.network.public_subnet_ids
}

output "app_logs_bucket_name" {
  description = "Name of the S3 bucket used for application logs."
  value       = aws_s3_bucket.app_logs.id
}

output "web_instance_ids" {
  description = "Instance IDs of the two web tier EC2 instances."
  value       = aws_instance.web[*].id
}

output "orphan_volume_id" {
  description = "ID of the intentionally unattached EBS volume (used to test the Cost Janitor)."
  value       = aws_ebs_volume.orphan.id
}
