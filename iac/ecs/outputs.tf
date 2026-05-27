output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "app_url" {
  value = var.domain_name != "" ? "https://${var.domain_name}" : "http://${module.alb.alb_dns}"
}

output "health_check" {
  value = var.domain_name != "" ? "curl https://${var.domain_name}/api/health" : "curl http://${module.alb.alb_dns}/api/health"
}
