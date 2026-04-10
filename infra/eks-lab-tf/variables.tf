# -----------------------------------------------------
# General
# -----------------------------------------------------
variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "agenticops-lab"
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-west-2"
}

variable "cluster_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.30"
}

# -----------------------------------------------------
# Network
# -----------------------------------------------------
variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnets" {
  description = "Private subnet CIDRs"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

variable "public_subnets" {
  description = "Public subnet CIDRs (NAT GW only)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

# -----------------------------------------------------
# Node Groups
# -----------------------------------------------------
variable "workload_instance_type" {
  description = "Instance type for workload node group"
  type        = string
  default     = "t3.large"
}

variable "workload_desired_size" {
  description = "Desired number of workload nodes"
  type        = number
  default     = 3
}

variable "workload_min_size" {
  description = "Minimum number of workload nodes"
  type        = number
  default     = 2
}

variable "workload_max_size" {
  description = "Maximum number of workload nodes"
  type        = number
  default     = 5
}

variable "monitoring_instance_type" {
  description = "Instance type for monitoring node group"
  type        = string
  default     = "t3.large"
}

variable "monitoring_desired_size" {
  description = "Desired number of monitoring nodes"
  type        = number
  default     = 2
}

variable "monitoring_min_size" {
  description = "Minimum number of monitoring nodes"
  type        = number
  default     = 1
}

variable "monitoring_max_size" {
  description = "Maximum number of monitoring nodes"
  type        = number
  default     = 3
}

# -----------------------------------------------------
# Karpenter
# -----------------------------------------------------
variable "karpenter_node_cpu_limit" {
  description = "Max vCPU Karpenter can provision"
  type        = number
  default     = 32
}

variable "karpenter_node_memory_limit" {
  description = "Max memory (Gi) Karpenter can provision"
  type        = string
  default     = "64Gi"
}

# -----------------------------------------------------
# Optional Addons
# -----------------------------------------------------
variable "enable_guardduty" {
  description = "Enable GuardDuty EKS Runtime Monitoring addon (requires GuardDuty enabled at account level)"
  type        = bool
  default     = false
}

# -----------------------------------------------------
# Monitoring
# -----------------------------------------------------
variable "grafana_admin_password" {
  description = "Grafana admin password"
  type        = string
  default     = "agenticops-lab"
  sensitive   = true
}

variable "alertmanager_webhook_url" {
  description = "AlertManager webhook URL for AgenticOps (empty = disabled)"
  type        = string
  default     = ""
}

# -----------------------------------------------------
# Tags
# -----------------------------------------------------
variable "tags" {
  description = "Additional tags for all resources"
  type        = map(string)
  default     = {}
}
