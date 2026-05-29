variable "project_name" {
  type = string
}

variable "service" {
  description = "Service type: ec2, ecs, or eks"
  type        = string
  validation {
    condition     = contains(["ec2", "ecs", "eks"], var.service)
    error_message = "service must be one of: ec2, ecs, eks"
  }
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "kms_key_arn" {
  description = "KMS key ARN for credential encryption. Empty = allow alias-based access."
  type        = string
  default     = ""
}

variable "dynamodb_enabled" {
  description = "Enable DynamoDB permissions (for state lock table)"
  type        = bool
  default     = false
}

variable "target_role_arns" {
  description = "List of target account role ARNs the app can assume. Empty = allow AgenticOps-* pattern."
  type        = list(string)
  default     = []
}

# EKS Pod Identity
variable "eks_cluster_name" {
  description = "EKS cluster name for Pod Identity association"
  type        = string
  default     = ""
}

variable "eks_namespace" {
  description = "Kubernetes namespace for Pod Identity"
  type        = string
  default     = "agenticops"
}

variable "eks_service_account" {
  description = "Kubernetes ServiceAccount name for Pod Identity"
  type        = string
  default     = "agenticops"
}
