# -----------------------------------------------------------------------------
# IAM Role for EC2 (SSM + Bedrock access)
# -----------------------------------------------------------------------------

resource "aws_iam_role" "ec2" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "bedrock" {
  name = "${var.project_name}-bedrock"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "sts:AssumeRole"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "iam:ResourceTag/agenticops" = "true"
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = "*"
      }
    ]
  })
}

# Read-only AWS access for scanning
resource "aws_iam_role_policy_attachment" "readonly" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# -----------------------------------------------------------------------------
# SSH Key Pair — auto-created from local pubkey if key_name not specified
# -----------------------------------------------------------------------------

resource "aws_key_pair" "app" {
  count      = var.key_name == "" ? 1 : 0
  key_name   = "${var.project_name}-key"
  public_key = file(pathexpand(var.ssh_public_key_path))
  tags       = local.tags
}

# -----------------------------------------------------------------------------
# EC2 Instance (public subnet with SSH access)
# -----------------------------------------------------------------------------

resource "aws_instance" "app" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = local.public_subnet_ids[0]
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  key_name                    = var.key_name != "" ? var.key_name : aws_key_pair.app[0].key_name
  associate_public_ip_address = true

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.ebs_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  user_data_base64 = base64encode(templatefile("${path.module}/user_data.sh", {
    app_port       = var.app_port
    bedrock_region = var.bedrock_region
    bedrock_model  = var.bedrock_model_id
    admin_password = var.admin_password
    project_name   = var.project_name
    git_branch     = var.git_branch
  }))

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only
  }

  tags = merge(local.tags, {
    Name = "${var.project_name}-app"
  })
}
