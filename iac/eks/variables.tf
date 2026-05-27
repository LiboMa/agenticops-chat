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

# --- Network ---
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

# --- EKS ---
variable "eks_cluster_name" {
  description = "Existing EKS cluster name. Empty = create new."
  type        = string
  default     = ""
}

variable "namespace" {
  type    = string
  default = "agenticops"
}

variable "replicas" {
  type    = number
  default = 1
}

variable "node_selector" {
  type    = map(string)
  default = {}
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
  type    = string
  default = "sqlite"
}

# --- DNS/SSL ---
variable "domain_name" {
  type    = string
  default = ""
}

variable "acm_cert_arn" {
  description = "ACM certificate ARN for HTTPS"
  type        = string
}

variable "route53_zone_id" {
  type    = string
  default = ""
}

variable "alb_internal" {
  type    = bool
  default = false
}
