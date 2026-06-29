terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Remote state. Create the bucket + DynamoDB lock table out-of-band (or via a
  # bootstrap workspace) before `terraform init`.
  backend "s3" {
    bucket         = "touchstone-tfstate"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "touchstone-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "touchstone"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
