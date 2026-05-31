##############################################################################
# AgenticOps IAM — Two-Layer Credential Architecture
#
# Layer 1 (Platform): Bedrock, S3, SNS, SES, CloudWatch, KMS, SSM, DynamoDB
#   → Attached directly to this role (EC2 Instance Profile / ECS Task Role / EKS Pod Identity)
#
# Layer 2 (Target Accounts): EC2, ECS, EKS, RDS, Lambda, CloudTrail, etc.
#   → Accessed via STS AssumeRole into target account roles
#   → This role only needs sts:AssumeRole permission
##############################################################################

locals {
  assume_role_service = {
    ec2 = "ec2.amazonaws.com"
    ecs = "ecs-tasks.amazonaws.com"
    eks = "pods.eks.amazonaws.com" # EKS Pod Identity (preferred over IRSA)
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

# --- IAM Role ---
resource "aws_iam_role" "this" {
  name = "${var.project_name}-${var.service}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [{
        Effect    = "Allow"
        Principal = { Service = local.assume_role_service[var.service] }
        Action    = var.service == "eks" ? ["sts:AssumeRole", "sts:TagSession"] : ["sts:AssumeRole"]
      }],
      # For EKS Pod Identity: allow the EKS service to assume
      var.service == "eks" ? [{
        Effect    = "Allow"
        Principal = { Service = "eks.amazonaws.com" }
        Action    = ["sts:AssumeRole", "sts:TagSession"]
      }] : []
    )
  })

  tags = var.tags
}

# --- Layer 1: Bedrock (AI Model Invocation) ---
resource "aws_iam_role_policy" "bedrock" {
  name = "${var.project_name}-bedrock"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:Converse",
          "bedrock:ConverseStream",
        ]
        Resource = [
          "arn:${data.aws_partition.current.partition}:bedrock:*::foundation-model/anthropic.*",
          "arn:${data.aws_partition.current.partition}:bedrock:*::foundation-model/amazon.*",
          "arn:${data.aws_partition.current.partition}:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*",
        ]
      },
      {
        Sid    = "BedrockList"
        Effect = "Allow"
        Action = [
          "bedrock:ListFoundationModels",
          "bedrock:GetFoundationModel",
        ]
        Resource = "*"
      },
    ]
  })
}

# --- Layer 1: S3 (Reports, KB, Storage) ---
resource "aws_iam_role_policy" "s3" {
  name = "${var.project_name}-s3"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3ReadWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          "arn:${data.aws_partition.current.partition}:s3:::${var.project_name}-*",
          "arn:${data.aws_partition.current.partition}:s3:::${var.project_name}-*/*",
        ]
      },
    ]
  })
}

# --- Layer 1: SNS + SES (Notifications) ---
resource "aws_iam_role_policy" "notifications" {
  name = "${var.project_name}-notifications"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SNS"
        Effect = "Allow"
        Action = [
          "sns:Publish",
          "sns:Subscribe",
          "sns:CreateTopic",
          "sns:GetTopicAttributes",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:sns:*:${data.aws_caller_identity.current.account_id}:${var.project_name}-*"
      },
      {
        Sid    = "SES"
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail",
        ]
        Resource = "*"
      },
    ]
  })
}

# --- Layer 1: CloudWatch (Logs + Metrics) ---
resource "aws_iam_role_policy" "cloudwatch" {
  name = "${var.project_name}-cloudwatch"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Logs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:*:${data.aws_caller_identity.current.account_id}:log-group:/${var.project_name}*"
      },
      {
        Sid    = "Metrics"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData",
          "cloudwatch:ListMetrics",
          "cloudwatch:PutMetricData",
        ]
        Resource = "*"
      },
    ]
  })
}

# --- Layer 1: KMS (Credential Encryption) ---
resource "aws_iam_role_policy" "kms" {
  name = "${var.project_name}-kms"
  role = aws_iam_role.this.id

  policy = var.kms_key_arn != "" ? jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "KMS"
      Effect   = "Allow"
      Action   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
      Resource = [var.kms_key_arn]
    }]
    }) : jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "KMS"
      Effect   = "Allow"
      Action   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
      Resource = ["arn:${data.aws_partition.current.partition}:kms:*:${data.aws_caller_identity.current.account_id}:alias/${var.project_name}"]
    }]
  })
}

# --- Layer 1: SSM (Parameter Store for secrets) ---
resource "aws_iam_role_policy" "ssm" {
  name = "${var.project_name}-ssm"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSM"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/*"
      },
    ]
  })
}

# --- Layer 1: DynamoDB (State lock, if used) ---
resource "aws_iam_role_policy" "dynamodb" {
  count = var.dynamodb_enabled ? 1 : 0
  name  = "${var.project_name}-dynamodb"
  role  = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:CreateTable",
          "dynamodb:DescribeTable",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:dynamodb:*:${data.aws_caller_identity.current.account_id}:table/${var.project_name}-*"
      },
    ]
  })
}

# --- Layer 1: ECR (Pull container images) ---
resource "aws_iam_role_policy" "ecr" {
  name = "${var.project_name}-ecr"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRPull"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:ecr:*:${data.aws_caller_identity.current.account_id}:repository/${var.project_name}*"
      },
    ]
  })
}

# --- Layer 2: STS AssumeRole into Target Accounts ---
resource "aws_iam_role_policy" "assume_target_accounts" {
  name = "${var.project_name}-assume-target"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AssumeTargetAccountRoles"
        Effect = "Allow"
        Action = [
          "sts:AssumeRole",
          "sts:GetCallerIdentity",
        ]
        Resource = length(var.target_role_arns) > 0 ? var.target_role_arns : [
          "arn:${data.aws_partition.current.partition}:iam::*:role/AgenticOps-*"
        ]
      },
    ]
  })
}

# --- EC2 Instance Profile (only for EC2 deployments) ---
resource "aws_iam_instance_profile" "this" {
  count = var.service == "ec2" ? 1 : 0
  name  = "${var.project_name}-${var.service}-profile"
  role  = aws_iam_role.this.name
}

# --- EKS Pod Identity Association (only for EKS deployments) ---
resource "aws_eks_pod_identity_association" "this" {
  count           = var.service == "eks" && var.eks_cluster_name != "" ? 1 : 0
  cluster_name    = var.eks_cluster_name
  namespace       = var.eks_namespace
  service_account = var.eks_service_account
  role_arn        = aws_iam_role.this.arn
}
