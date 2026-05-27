output "endpoint" {
  value = var.enabled ? aws_db_instance.this[0].endpoint : ""
}

output "database_url" {
  value     = var.enabled ? "postgresql+psycopg2://agenticops:${local.password}@${aws_db_instance.this[0].endpoint}/agenticops" : ""
  sensitive = true
}

output "password" {
  value     = var.enabled ? local.password : ""
  sensitive = true
}
