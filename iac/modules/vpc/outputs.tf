output "vpc_id" {
  value = local.create_vpc ? aws_vpc.this[0].id : var.vpc_id
}

output "public_subnet_ids" {
  value = local.create_vpc ? aws_subnet.public[*].id : (
    length(var.public_subnet_ids) > 0 ? var.public_subnet_ids : try(data.aws_subnets.public[0].ids, [])
  )
}

output "private_subnet_ids" {
  value = local.create_vpc ? aws_subnet.private[*].id : (
    length(var.private_subnet_ids) > 0 ? var.private_subnet_ids : try(data.aws_subnets.private[0].ids, [])
  )
}
