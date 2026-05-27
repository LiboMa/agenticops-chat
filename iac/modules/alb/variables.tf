variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "domain_name" {
  description = "Custom domain name (used for auto-cert creation with Route53)"
  type        = string
  default     = ""
}

variable "acm_cert_arn" {
  description = "ACM certificate ARN for HTTPS. If empty + domain + zone set, auto-creates cert."
  type        = string
}

variable "route53_zone_id" {
  description = "Route53 zone ID for ACM DNS validation"
  type        = string
  default     = ""
}

variable "internal" {
  description = "Internal ALB (true) or internet-facing (false)"
  type        = bool
  default     = false
}

variable "target_port" {
  type    = number
  default = 8000
}

variable "health_check_path" {
  type    = string
  default = "/api/health"
}

variable "tags" {
  type    = map(string)
  default = {}
}
