output "vpc_id" {
  description = "ID of the created VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets, in the same order as var.public_subnet_cidrs."
  value       = aws_subnet.public[*].id
}
