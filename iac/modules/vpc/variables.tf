variable "project_name" {
  type = string
}

variable "vpc_id" {
  description = "Existing VPC ID. Empty = create new."
  type        = string
  default     = ""
}

variable "public_subnet_ids" {
  description = "Existing public subnet IDs (required if vpc_id set)"
  type        = list(string)
  default     = []
}

variable "private_subnet_ids" {
  description = "Existing private subnet IDs (required if vpc_id set)"
  type        = list(string)
  default     = []
}

variable "vpc_cidr" {
  description = "CIDR for new VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones (auto-detected if empty)"
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
