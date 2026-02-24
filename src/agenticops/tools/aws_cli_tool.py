"""AWS CLI Tool — execute AWS CLI commands with safety controls.

Provides two tools:
- run_aws_cli: Full AWS CLI access for the Main Agent (read + write with confirmation).
- run_aws_cli_readonly: Read-only AWS CLI access for sub-agents (no write/destructive ops).

Both share a three-tier security model: read-only (auto), write (confirmation required),
and blocked (dangerous operations rejected outright).
"""

from __future__ import annotations

import logging
import shlex
import subprocess

from strands import tool

logger = logging.getLogger(__name__)

# ── Security tiers ───────────────────────────────────────────────────

READONLY_PREFIXES = [
    # EC2
    "aws ec2 describe-", "aws ec2 get-",
    # ECS
    "aws ecs describe-", "aws ecs list-",
    # EKS
    "aws eks describe-", "aws eks list-",
    # RDS
    "aws rds describe-",
    # Lambda
    "aws lambda get-", "aws lambda list-",
    # ELB
    "aws elbv2 describe-",
    # S3
    "aws s3 ls", "aws s3api get-", "aws s3api list-", "aws s3api head-",
    # CloudWatch
    "aws cloudwatch describe-", "aws cloudwatch get-", "aws cloudwatch list-",
    # CloudTrail
    "aws cloudtrail lookup-", "aws cloudtrail describe-", "aws cloudtrail get-",
    # IAM
    "aws iam get-", "aws iam list-",
    # STS
    "aws sts get-",
    # Route53
    "aws route53 list-", "aws route53 get-",
    # CloudWatch Logs
    "aws logs describe-", "aws logs get-", "aws logs filter-",
    # SQS
    "aws sqs get-", "aws sqs list-",
    # SNS
    "aws sns get-", "aws sns list-",
    # DynamoDB
    "aws dynamodb describe-", "aws dynamodb list-",
    # Auto Scaling
    "aws autoscaling describe-",
    # SSM
    "aws ssm describe-", "aws ssm get-", "aws ssm list-",
    # CloudFront
    "aws cloudfront get-", "aws cloudfront list-",
    # WAFv2
    "aws wafv2 get-", "aws wafv2 list-",
    # Config
    "aws config describe-", "aws config get-",
    # ElastiCache
    "aws elasticache describe-", "aws elasticache list-",
    # Redshift
    "aws redshift describe-", "aws redshift list-",
    # Step Functions
    "aws stepfunctions describe-", "aws stepfunctions list-",
    "aws stepfunctions get-",
    # API Gateway (v1)
    "aws apigateway get-",
    # API Gateway v2
    "aws apigatewayv2 get-",
    # Kinesis
    "aws kinesis describe-", "aws kinesis list-",
    # Firehose
    "aws firehose describe-", "aws firehose list-",
    # OpenSearch
    "aws opensearch describe-", "aws opensearch list-",
    # ACM
    "aws acm describe-", "aws acm list-", "aws acm get-",
    # KMS
    "aws kms describe-", "aws kms list-", "aws kms get-",
    # Secrets Manager
    "aws secretsmanager describe-", "aws secretsmanager list-",
    "aws secretsmanager get-secret-value",
    # ECR
    "aws ecr describe-", "aws ecr list-", "aws ecr get-",
    # CodePipeline
    "aws codepipeline get-", "aws codepipeline list-",
    # CodeBuild
    "aws codebuild batch-get-", "aws codebuild list-",
    # CodeCommit
    "aws codecommit get-", "aws codecommit list-",
    # GuardDuty
    "aws guardduty get-", "aws guardduty list-",
    # Inspector
    "aws inspector2 list-", "aws inspector2 get-",
    # Security Hub
    "aws securityhub get-", "aws securityhub list-",
    "aws securityhub describe-",
    # Service Quotas
    "aws service-quotas get-", "aws service-quotas list-",
    # Health
    "aws health describe-",
    # Support
    "aws support describe-",
    # Cost Explorer
    "aws ce get-",
    # Organizations (read-only)
    "aws organizations describe-", "aws organizations list-",
    # Resource Groups Tagging
    "aws resourcegroupstaggingapi get-",
    # Backup
    "aws backup describe-", "aws backup list-", "aws backup get-",
    # Glue
    "aws glue get-", "aws glue list-",
    # Athena
    "aws athena get-", "aws athena list-",
    # EMR
    "aws emr describe-", "aws emr list-",
]

WRITE_PREFIXES = [
    "aws ec2 create-", "aws ec2 modify-", "aws ec2 delete-",
    "aws ec2 start-", "aws ec2 stop-", "aws ec2 reboot-",
    "aws ec2 associate-", "aws ec2 disassociate-",
    "aws ec2 attach-", "aws ec2 detach-",
    "aws ecs update-", "aws ecs create-", "aws ecs delete-",
    "aws rds modify-", "aws rds reboot-", "aws rds create-", "aws rds delete-",
    "aws lambda update-",
    "aws s3 cp", "aws s3 mv", "aws s3 rm", "aws s3 sync",
    "aws autoscaling update-", "aws autoscaling set-",
    "aws ssm send-command",
]

BLOCKED_PATTERNS = [
    "aws iam create-user", "aws iam delete-user",
    "aws iam create-access-key", "aws iam attach-",
    # Organizations — block destructive subcommands, allow read-only (describe/list)
    "aws organizations create-", "aws organizations delete-",
    "aws organizations move-", "aws organizations invite-",
    "aws organizations leave-", "aws organizations remove-",
    # Account — block destructive subcommands
    "aws account close-", "aws account delete-",
    "--force",
    "| rm", "; rm", "&& rm",
    "aws ec2 terminate-instances",
]

MAX_OUTPUT_CHARS = 4000
MAX_OUTPUT_CHARS_READONLY = 8000
TIMEOUT_SECONDS = 30


def _classify_command(command: str) -> str:
    """Classify a command as 'blocked', 'write', 'readonly', or 'unknown'."""
    cmd_lower = command.lower().strip()

    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return "blocked"

    for prefix in WRITE_PREFIXES:
        if cmd_lower.startswith(prefix.lower()):
            return "write"

    for prefix in READONLY_PREFIXES:
        if cmd_lower.startswith(prefix.lower()):
            return "readonly"

    return "unknown"


def _execute_aws_cli(command: str, max_chars: int) -> str:
    """Shared execution logic for both AWS CLI tools.

    Assumes command has already been validated (starts with 'aws', no shell injection).
    Appends --output json if needed, executes via subprocess, truncates output.
    """
    # Auto-append --output json if not specified
    if "--output" not in command:
        command = f"{command} --output json"

    try:
        args = shlex.split(command)
    except ValueError as e:
        return f"Error: Invalid command syntax: {e}"

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {TIMEOUT_SECONDS} seconds."
    except FileNotFoundError:
        return "Error: AWS CLI not found. Please ensure 'aws' is installed and on PATH."

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if len(stderr) > max_chars:
            stderr = stderr[:max_chars] + "\n... (output truncated)"
        return f"Error (exit code {result.returncode}): {stderr}"

    output = result.stdout.strip()
    if len(output) > max_chars:
        output = output[:max_chars] + "\n... (output truncated)"

    return output if output else "(no output)"


@tool
def run_aws_cli(command: str, require_confirmation: bool = False) -> str:
    """Execute an AWS CLI command and return the output.

    Use this tool to run any AWS CLI command for querying or managing AWS resources.
    The command must start with 'aws'. Output is returned as JSON when possible.

    Read-only commands (describe, list, get) are executed directly.
    Write commands (create, modify, delete, update) require explicit confirmation.
    Destructive commands (terminate, delete IAM) are blocked for safety.

    Args:
        command: The full AWS CLI command (e.g., 'aws ec2 describe-instances --region us-east-1')
        require_confirmation: Set to true to acknowledge a write operation

    Returns:
        JSON output from the AWS CLI command, or error message.

    Examples:
        run_aws_cli(command="aws ec2 describe-instances --region us-east-1 --output json")
        run_aws_cli(command="aws ecs list-services --cluster my-cluster --output json")
        run_aws_cli(command="aws logs filter-log-events --log-group-name /aws/lambda/my-fn --start-time 1700000000000 --output json")
    """
    command = command.strip()

    # 1. Must start with "aws "
    if not command.startswith("aws "):
        return "Error: Command must start with 'aws'. Example: aws ec2 describe-instances --region us-east-1"

    # 2. Check for shell injection patterns
    for dangerous in ["|", ";", "&&", "$(", "`", ">", "<"]:
        if dangerous in command:
            return f"Error: Shell operators ({dangerous}) are not allowed in AWS CLI commands for security reasons."

    # 3. Classify and enforce security tier
    tier = _classify_command(command)

    if tier == "blocked":
        return (
            f"Error: This command is blocked for safety. "
            f"Destructive operations like IAM user management and instance termination "
            f"are not allowed through this tool. Command: {command}"
        )

    if tier in ("write", "unknown") and not require_confirmation:
        return (
            f"This is a write operation that requires confirmation. "
            f"Please present the command to the user, explain what it will do, "
            f"and call again with require_confirmation=True after getting approval. "
            f"Command: {command}"
        )

    # 4. Execute
    return _execute_aws_cli(command, MAX_OUTPUT_CHARS)


@tool
def run_aws_cli_readonly(command: str) -> str:
    """Execute a read-only AWS CLI command. Write and destructive operations are blocked.

    Use this as a fallback for querying AWS services not covered by specialized tools.
    Only read-only commands (describe, list, get) are accepted — all write, destructive,
    and unrecognized commands are rejected.

    Args:
        command: The full AWS CLI command (e.g., 'aws elasticache describe-cache-clusters --output json')

    Returns:
        JSON output from the AWS CLI command, or error message.

    Examples:
        run_aws_cli_readonly(command="aws elasticache describe-cache-clusters --region us-east-1")
        run_aws_cli_readonly(command="aws redshift describe-clusters --region us-west-2")
        run_aws_cli_readonly(command="aws stepfunctions list-state-machines --region us-east-1")
        run_aws_cli_readonly(command="aws apigatewayv2 get-apis --region us-east-1")
    """
    command = command.strip()

    # 1. Must start with "aws "
    if not command.startswith("aws "):
        return "Error: Command must start with 'aws'. Example: aws elasticache describe-cache-clusters --region us-east-1"

    # 2. Check for shell injection patterns
    for dangerous in ["|", ";", "&&", "$(", "`", ">", "<"]:
        if dangerous in command:
            return f"Error: Shell operators ({dangerous}) are not allowed in AWS CLI commands for security reasons."

    # 3. Must be classified as readonly — reject everything else
    tier = _classify_command(command)

    if tier != "readonly":
        return (
            f"Error: Only read-only commands are allowed (describe, list, get). "
            f"This command was classified as '{tier}' and is rejected. "
            f"Command: {command}"
        )

    # 4. Execute with larger output limit for deeper investigation
    return _execute_aws_cli(command, MAX_OUTPUT_CHARS_READONLY)
