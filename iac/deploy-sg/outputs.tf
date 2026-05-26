# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "app_url" {
  description = "Application URL (custom domain)"
  value       = "https://${var.domain_name}"
}

output "cloudfront_url" {
  description = "CloudFront distribution URL (HTTPS)"
  value       = "https://${aws_cloudfront_distribution.app.domain_name}"
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.app.id
}

output "alb_dns_name" {
  description = "ALB DNS name (internal, do not expose directly)"
  value       = aws_lb.app.dns_name
}

output "ec2_instance_id" {
  description = "EC2 instance ID (use with SSM)"
  value       = aws_instance.app.id
}

output "vpc_id" {
  description = "VPC ID used for deployment"
  value       = local.vpc_id
}

output "ec2_public_ip" {
  description = "EC2 public IP address"
  value       = aws_instance.app.public_ip
}

output "ssh_command" {
  description = "SSH command to connect"
  value       = "ssh ubuntu@${aws_instance.app.public_ip}"
}

output "ssm_command" {
  description = "SSM session command"
  value       = "aws ssm start-session --target ${aws_instance.app.id} --region ${var.region}"
}
