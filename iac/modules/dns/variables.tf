variable "domain_name" {
  type    = string
  default = ""
}

variable "route53_zone_id" {
  type    = string
  default = ""
}

variable "target_dns" {
  description = "ALB DNS name to point to"
  type        = string
}

variable "target_zone_id" {
  description = "ALB hosted zone ID"
  type        = string
}
