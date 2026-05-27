output "role_arn" {
  value = aws_iam_role.this.arn
}

output "role_name" {
  value = aws_iam_role.this.name
}

output "instance_profile_name" {
  value = var.service == "ec2" ? aws_iam_instance_profile.this[0].name : ""
}
