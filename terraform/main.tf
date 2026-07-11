# miniAI AWS layer — everything cloud-side is code.
#
#   terraform init && terraform plan && terraform apply
#
# Resources: SSM parameters (all app config + the demo token), a least-
# privilege IAM user for the mini, and optional Route 53 DNS. Monthly cost:
# ~$0.50 (hosted zone) — SSM standard tier and IAM are free.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state: versioned S3 bucket (created one-time by hand — the classic
  # backend chicken-and-egg). Secrets in state stay out of git entirely.
  backend "s3" {
    bucket       = "cmurray-miniai-tfstate"
    key          = "miniai/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true # S3-native state locking (no DynamoDB table needed)
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "miniAI"
      ManagedBy = "terraform"
    }
  }
}
