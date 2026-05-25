terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "agenticops"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# CloudFront requires ACM certs in us-east-1, but we use default domain
# Keep this provider for future custom domain support
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
