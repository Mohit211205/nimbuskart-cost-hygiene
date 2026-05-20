variable "region" {
  type        = string
  description = "AWS region to deploy resources in."
  default     = "us-east-1"
}

variable "project" {
  type        = string
  description = "Project name used in resource names and the Project tag."
  default     = "nimbuskart"
}

variable "environment" {
  type        = string
  description = "Deployment environment (staging, production)."
  default     = "staging"
}

variable "owner" {
  type        = string
  description = "Team or individual responsible for these resources (Owner tag)."
  default     = "platform-team"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC."
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for the two public subnets."
  default     = ["10.20.1.0/24", "10.20.2.0/24"]
}

variable "availability_zones" {
  type        = list(string)
  description = "Availability zones for subnet placement."
  default     = ["us-east-1a", "us-east-1b"]
}

variable "ssh_allowed_cidr" {
  type        = string
  description = "CIDR that may reach port 22. Defaults to RFC-1918 private range; override to a specific bastion or VPN CIDR in production."
  default     = "10.0.0.0/8"
}

variable "ami_id" {
  type        = string
  description = "AMI ID for web tier EC2 instances. Any non-empty string works against LocalStack."
  default     = "ami-0c55b159cbfafe1f0"
}
