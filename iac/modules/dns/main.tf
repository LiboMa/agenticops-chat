locals {
  create = var.domain_name != "" && var.route53_zone_id != ""
}

resource "aws_route53_record" "this" {
  count   = local.create ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = var.target_dns
    zone_id                = var.target_zone_id
    evaluate_target_health = true
  }
}
