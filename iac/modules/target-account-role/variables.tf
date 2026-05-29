variable "trusted_account_id" {
  description = "AWS account ID where AgenticOps platform is deployed"
  type        = string
}

variable "external_id" {
  description = "External ID for AssumeRole (recommended for third-party access)"
  type        = string
  default     = ""
}

variable "role_name_prefix" {
  description = "IAM role name prefix"
  type        = string
  default     = "AgenticOps"
}

variable "environment" {
  description = "Environment suffix (e.g., prod, staging)"
  type        = string
  default     = "prod"
}

variable "executor_enabled" {
  description = "Allow SSM Run Command for automated remediation"
  type        = bool
  default     = false
}

variable "billing_enabled" {
  description = "Allow Cost Explorer read access"
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
