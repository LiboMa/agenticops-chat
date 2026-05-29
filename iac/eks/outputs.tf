output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "cluster_name" {
  value = var.eks_cluster_name
}

output "namespace" {
  value = var.namespace
}

output "role_arn" {
  description = "IAM role ARN (for Pod Identity)"
  value       = module.iam.role_arn
}

output "app_url" {
  value = var.domain_name != "" ? "https://${var.domain_name}" : "kubectl port-forward svc/${var.project_name} 8000:8000 -n ${var.namespace}"
}
