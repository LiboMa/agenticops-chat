output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "public_ip" {
  value = aws_instance.this.public_ip
}

output "app_url" {
  value = var.domain_name != "" ? "https://${var.domain_name}" : "https://${module.alb.alb_dns}"
}

output "ssh_command" {
  value = var.ssh_enabled ? "ssh ubuntu@${aws_instance.this.public_ip}" : "SSH disabled"
}

output "health_check" {
  value = var.domain_name != "" ? "curl -k https://${var.domain_name}/api/health" : "curl -k https://${module.alb.alb_dns}/api/health"
}

output "alb_internal" {
  value = var.alb_internal ? "internal (VPC only)" : "internet-facing (public)"
}
