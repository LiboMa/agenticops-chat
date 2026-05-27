variable "enabled" {
  type    = bool
  default = false
}

variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "instance_class" {
  type    = string
  default = "db.t3.medium"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "password" {
  description = "Master password. Empty = auto-generate."
  type        = string
  default     = ""
  sensitive   = true
}

variable "allowed_security_group_id" {
  description = "SG allowed to connect to RDS"
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
