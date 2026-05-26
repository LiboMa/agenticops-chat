# -----------------------------------------------------------------------------
# Security Groups
# -----------------------------------------------------------------------------

# ALB — only accepts traffic from CloudFront (via managed prefix list)
resource "aws_security_group" "alb" {
  name_prefix = "${var.project_name}-alb-"
  description = "ALB - allow inbound from CloudFront only"
  vpc_id      = local.vpc_id

  tags = merge(local.tags, { Name = "${var.project_name}-alb-sg" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "alb_ingress_cf" {
  type              = "ingress"
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  prefix_list_ids   = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from CloudFront"
}

resource "aws_security_group_rule" "alb_egress" {
  type                     = "egress"
  from_port                = var.app_port
  to_port                  = var.app_port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ec2.id
  security_group_id        = aws_security_group.alb.id
  description              = "To EC2 app port"
}

# EC2 — only accepts traffic from ALB on app port
resource "aws_security_group" "ec2" {
  name_prefix = "${var.project_name}-ec2-"
  description = "EC2 - allow inbound from ALB only"
  vpc_id      = local.vpc_id

  tags = merge(local.tags, { Name = "${var.project_name}-ec2-sg" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "ec2_ingress_alb" {
  type                     = "ingress"
  from_port                = var.app_port
  to_port                  = var.app_port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  security_group_id        = aws_security_group.ec2.id
  description              = "App port from ALB"
}

resource "aws_security_group_rule" "ec2_ingress_ssh" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = var.ssh_allowed_cidrs
  security_group_id = aws_security_group.ec2.id
  description       = "SSH from allowed CIDRs"
}

resource "aws_security_group_rule" "ec2_egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ec2.id
  description       = "Outbound all (Bedrock API, pip, etc.)"
}
