# -----------------------------------------------------------------------------
# General
# -----------------------------------------------------------------------------

variable "region" {
  description = "AWS region for deployment"
  type        = string
  default     = "ap-southeast-1"
}

variable "environment" {
  description = "Environment name (dev/staging/prod)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "agenticops"
}

# -----------------------------------------------------------------------------
# Network — set vpc_id to use existing VPC, leave empty to create new
# -----------------------------------------------------------------------------

variable "vpc_id" {
  description = "Existing VPC ID. Leave empty to create a new VPC."
  type        = string
  default     = ""
}

variable "vpc_cidr" {
  description = "CIDR block for new VPC (ignored if vpc_id is set)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_ids" {
  description = "Existing public subnet IDs for ALB (required if vpc_id is set)"
  type        = list(string)
  default     = []
}

variable "private_subnet_ids" {
  description = "Existing private subnet IDs for EC2 (required if vpc_id is set)"
  type        = list(string)
  default     = []
}

# -----------------------------------------------------------------------------
# EC2
# -----------------------------------------------------------------------------

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "c5.xlarge"
}

variable "key_name" {
  description = "SSH key pair name (optional, auto-created from local pubkey if empty)"
  type        = string
  default     = ""
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key file for EC2 access"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed to SSH (default: anywhere)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "ebs_volume_size" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 30
}

# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------

variable "app_port" {
  description = "Application listening port"
  type        = number
  default     = 8000
}

variable "bedrock_region" {
  description = "AWS Bedrock region for LLM calls"
  type        = string
  default     = "us-east-1"
}

variable "bedrock_model_id" {
  description = "Default Bedrock model ID"
  type        = string
  default     = "global.anthropic.claude-opus-4-6-v1"
}

variable "admin_password" {
  description = "Default admin user password"
  type        = string
  default     = "aiops2026"
  sensitive   = true
}

variable "git_branch" {
  description = "Git branch to deploy"
  type        = string
  default     = "main"
}

# -----------------------------------------------------------------------------
# DNS & SSL
# -----------------------------------------------------------------------------

variable "domain_name" {
  description = "Custom domain name for CloudFront"
  type        = string
  default     = "agenticops.tinyboat.blog"
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN (must be in us-east-1 for CloudFront)"
  type        = string
  default     = "arn:aws:acm:us-east-1:533267047935:certificate/58547364-f524-4695-a3b8-3e990c6263b1"
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID"
  type        = string
  default     = "Z02657523IKMDPFJE34YX"
}

# -----------------------------------------------------------------------------
# Tags
# -----------------------------------------------------------------------------

variable "extra_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
