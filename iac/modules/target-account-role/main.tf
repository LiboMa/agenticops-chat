##############################################################################
# AgenticOps Target Account Role
#
# Deploy this module in each AWS account that AgenticOps needs to scan/manage.
# It creates a read-only role that the AgenticOps platform can AssumeRole into.
#
# Usage:
#   module "agenticops_role" {
#     source               = "../modules/target-account-role"
#     trusted_account_id   = "533267047935"  # AgenticOps platform account
#     external_id          = "agenticops-xyz" # Optional: external ID for security
#   }
##############################################################################

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

resource "aws_iam_role" "this" {
  name = "${var.role_name_prefix}-${var.environment}"
  path = "/"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        AWS = "arn:${data.aws_partition.current.partition}:iam::${var.trusted_account_id}:root"
      }
      Action = "sts:AssumeRole"
      Condition = var.external_id != "" ? {
        StringEquals = { "sts:ExternalId" = var.external_id }
      } : {}
    }]
  })

  max_session_duration = 3600

  tags = merge(var.tags, {
    Purpose = "AgenticOps cross-account scanning"
  })
}

# --- Read-Only: Compute & Networking ---
resource "aws_iam_role_policy" "compute_read" {
  name = "compute-networking-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2Read"
        Effect = "Allow"
        Action = [
          "ec2:Describe*",
          "ec2:Get*",
          "ec2:List*",
        ]
        Resource = "*"
      },
      {
        Sid    = "ECSRead"
        Effect = "Allow"
        Action = [
          "ecs:Describe*",
          "ecs:List*",
        ]
        Resource = "*"
      },
      {
        Sid    = "EKSRead"
        Effect = "Allow"
        Action = [
          "eks:Describe*",
          "eks:List*",
        ]
        Resource = "*"
      },
      {
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = [
          "lambda:List*",
          "lambda:Get*",
        ]
        Resource = "*"
      },
      {
        Sid    = "ELBRead"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:Describe*",
        ]
        Resource = "*"
      },
    ]
  })
}

# --- Read-Only: Data & Storage ---
resource "aws_iam_role_policy" "data_read" {
  name = "data-storage-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RDSRead"
        Effect = "Allow"
        Action = [
          "rds:Describe*",
          "rds:List*",
        ]
        Resource = "*"
      },
      {
        Sid    = "DynamoDBRead"
        Effect = "Allow"
        Action = [
          "dynamodb:Describe*",
          "dynamodb:List*",
        ]
        Resource = "*"
      },
      {
        Sid    = "S3Read"
        Effect = "Allow"
        Action = [
          "s3:GetBucketLocation",
          "s3:GetBucketPolicy",
          "s3:GetBucketAcl",
          "s3:GetEncryptionConfiguration",
          "s3:GetBucketVersioning",
          "s3:GetBucketPublicAccessBlock",
          "s3:ListBucket",
          "s3:ListAllMyBuckets",
        ]
        Resource = "*"
      },
    ]
  })
}

# --- Read-Only: Security & Compliance ---
resource "aws_iam_role_policy" "security_read" {
  name = "security-compliance-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IAMRead"
        Effect = "Allow"
        Action = [
          "iam:Get*",
          "iam:List*",
          "iam:GenerateCredentialReport",
          "iam:GetCredentialReport",
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudTrailRead"
        Effect = "Allow"
        Action = [
          "cloudtrail:Describe*",
          "cloudtrail:Get*",
          "cloudtrail:List*",
          "cloudtrail:LookupEvents",
        ]
        Resource = "*"
      },
      {
        Sid    = "ConfigRead"
        Effect = "Allow"
        Action = [
          "config:Describe*",
          "config:Get*",
          "config:List*",
        ]
        Resource = "*"
      },
      {
        Sid    = "GuardDutyRead"
        Effect = "Allow"
        Action = [
          "guardduty:Get*",
          "guardduty:List*",
        ]
        Resource = "*"
      },
      {
        Sid    = "SecurityHubRead"
        Effect = "Allow"
        Action = [
          "securityhub:Get*",
          "securityhub:List*",
          "securityhub:Describe*",
        ]
        Resource = "*"
      },
    ]
  })
}

# --- Read-Only: Monitoring & Observability ---
resource "aws_iam_role_policy" "monitoring_read" {
  name = "monitoring-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:Describe*",
          "cloudwatch:Get*",
          "cloudwatch:List*",
          "logs:Describe*",
          "logs:Get*",
          "logs:FilterLogEvents",
          "logs:StartQuery",
          "logs:StopQuery",
          "logs:GetQueryResults",
        ]
        Resource = "*"
      },
      {
        Sid    = "SNSRead"
        Effect = "Allow"
        Action = [
          "sns:Get*",
          "sns:List*",
        ]
        Resource = "*"
      },
    ]
  })
}

# --- Execution: SSM Run Command (only if executor enabled) ---
resource "aws_iam_role_policy" "executor" {
  count = var.executor_enabled ? 1 : 0
  name  = "executor-ssm"
  role  = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMExec"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand",
          "ssm:GetCommandInvocation",
          "ssm:ListCommandInvocations",
        ]
        Resource = "*"
      },
    ]
  })
}

# --- Billing (optional) ---
resource "aws_iam_role_policy" "billing" {
  count = var.billing_enabled ? 1 : 0
  name  = "billing-read"
  role  = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CostExplorer"
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetCostForecast",
          "ce:GetReservationUtilization",
          "ce:GetSavingsPlansUtilization",
        ]
        Resource = "*"
      },
    ]
  })
}
