terraform {
  required_version = ">= 1.3"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# When using the tflocal wrapper, endpoint URLs are injected automatically.
# When running plain terraform against a real AWS account, remove the
# override variables below and ensure standard AWS credentials are configured.
provider "aws" {
  region = var.region

  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    Owner       = var.owner
    ManagedBy   = "terraform"
  }
}

module "network" {
  source              = "./modules/network"
  vpc_cidr            = var.vpc_cidr
  public_subnet_cidrs = var.public_subnet_cidrs
  availability_zones  = var.availability_zones
  project             = var.project
  environment         = var.environment
  common_tags         = local.common_tags
}

resource "aws_security_group" "web" {
  name        = "${var.project}-${var.environment}-web-sg"
  description = "Security group for the web tier."
  vpc_id      = module.network.vpc_id

  ingress {
    description = "HTTP from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # DEVIATION: The brief defaults ssh_allowed_cidr to 0.0.0.0/0.
  # That would expose SSH to the entire internet — a critical risk.
  # The variable is kept configurable, but the default is set to
  # the RFC-1918 private range (10.0.0.0/8) so misconfigurations
  # require an explicit override. See README "Decisions & deviations".
  ingress {
    description = "SSH from approved CIDR only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_allowed_cidr]
  }

  egress {
    description = "All outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-web-sg"
  })
}

resource "aws_instance" "web" {
  count         = 2
  ami           = var.ami_id
  instance_type = "t3.micro"
  subnet_id     = module.network.public_subnet_ids[count.index]

  vpc_security_group_ids = [aws_security_group.web.id]

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-web-${count.index + 1}"
    Tier = "web"
  })
}

resource "aws_s3_bucket" "app_logs" {
  bucket = "${var.project}-${var.environment}-app-logs"

  tags = local.common_tags
}

resource "aws_s3_bucket_versioning" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "app_logs" {
  bucket     = aws_s3_bucket.app_logs.id
  depends_on = [aws_s3_bucket_versioning.app_logs]

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# This volume is intentionally left unattached to act as a known orphan
# for validating the Cost Janitor in Part B.
resource "aws_ebs_volume" "orphan" {
  availability_zone = var.availability_zones[0]
  size              = 10
  type              = "gp3"

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-orphan-vol"
    Note = "intentionally-unattached-test-resource"
  })
}
