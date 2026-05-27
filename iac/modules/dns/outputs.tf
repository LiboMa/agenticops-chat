output "fqdn" {
  value = local.create ? aws_route53_record.this[0].fqdn : ""
}
