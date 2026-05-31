output "role_arn" {
  description = "ARN of the target account role — add this to AgenticOps WebUI"
  value       = aws_iam_role.this.arn
}

output "role_name" {
  value = aws_iam_role.this.name
}
