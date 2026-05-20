variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC."
}

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for the public subnets (one per AZ)."
}

variable "availability_zones" {
  type        = list(string)
  description = "Availability zones — must match the number of public_subnet_cidrs entries."
}

variable "project" {
  type        = string
  description = "Project name used in resource names and tags."
}

variable "environment" {
  type        = string
  description = "Deployment environment (staging, production, etc.)."
}

variable "common_tags" {
  type        = map(string)
  description = "Tags to propagate to every resource in this module."
  default     = {}
}
