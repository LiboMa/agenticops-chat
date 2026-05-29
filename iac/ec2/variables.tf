# --- General ---
variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "project_name" {
  type    = string
  default = "agenticops"
}

variable "image_tag" {
  type    = string
  default = "latest"
}

# --- Network (bring-your-own) ---
variable "vpc_id" {
  type    = string
  default = ""
}

variable "public_subnet_ids" {
  type    = list(string)
  default = []
}

variable "private_subnet_ids" {
  type    = list(string)
  default = []
}

# --- EC2 ---
variable "instance_type" {
  type    = string
  default = "c5.xlarge"
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_rsa.pub"
}

variable "ssh_enabled" {
  description = "Enable SSH access (requires ssh_public_key_path to exist)"
  type        = bool
  default     = false
}

variable "ssh_allowed_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

# --- App ---
variable "bedrock_region" {
  type    = string
  default = "us-east-1"
}

variable "bedrock_model" {
  type    = string
  default = "global.anthropic.claude-sonnet-4-6"
}

variable "bedrock_model_strong" {
  type    = string
  default = "global.anthropic.claude-opus-4-6-v1"
}

variable "bedrock_model_cheap" {
  type    = string
  default = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "admin_password" {
  type      = string
  sensitive = true
}

# --- Database ---
variable "db_backend" {
  description = "sqlite or rds"
  type        = string
  default     = "sqlite"
}

# --- DNS/SSL (HTTPS always on 443) ---
variable "domain_name" {
  description = "Custom domain. Set with route53_zone_id for auto-cert."
  type        = string
  default     = ""
}

variable "acm_cert_arn" {
  description = "ACM certificate ARN for HTTPS. Required unless domain+zone provided for auto-cert."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route53 zone ID for DNS record + auto-cert validation"
  type        = string
  default     = ""
}

variable "alb_internal" {
  type    = bool
  default = false
}

# --- Security ---
variable "kms_key_arn" {
  description = "KMS key ARN for credential encryption at rest"
  type        = string
  default     = ""
}

variable "target_role_arns" {
  description = "Explicit list of target account role ARNs. Empty = allow AgenticOps-* pattern."
  type        = list(string)
  default     = []
}
