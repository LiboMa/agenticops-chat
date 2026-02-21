"""AWS CLI Tool — execute AWS CLI commands with safety controls.

Provides the main Agent with direct AWS CLI access, constrained by a
three-tier security model: read-only (auto), write (confirmation required),
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
    "aws ec2 describe-", "aws ec2 get-",
    "aws ecs describe-", "aws ecs list-",
    "aws eks describe-", "aws eks list-",
    "aws rds describe-",
    "aws lambda get-", "aws lambda list-",
    "aws elbv2 describe-",
    "aws s3 ls", "aws s3api get-", "aws s3api list-", "aws s3api head-",
    "aws cloudwatch describe-", "aws cloudwatch get-", "aws cloudwatch list-",
    "aws cloudtrail lookup-",
    "aws iam get-", "aws iam list-",
    "aws sts get-",
    "aws route53 list-", "aws route53 get-",
    "aws logs describe-", "aws logs get-", "aws logs filter-",
    "aws sqs get-", "aws sqs list-",
    "aws sns get-", "aws sns list-",
    "aws dynamodb describe-", "aws dynamodb list-",
    "aws autoscaling describe-",
    "aws ssm describe-", "aws ssm get-", "aws ssm list-",
    "aws cloudfront get-", "aws cloudfront list-",
    "aws wafv2 get-", "aws wafv2 list-",
    "aws config describe-", "aws config get-",
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
    "aws organizations", "aws account",
    "--force",
    "| rm", "; rm", "&& rm",
    "aws ec2 terminate-instances",
]

MAX_OUTPUT_CHARS = 4000
TIMEOUT_SECONDS = 30


def _classify_command(command: str) -> str:
    """Classify a command as 'blocked', 'write', or 'readonly'."""
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

    # Unknown commands default to write (require confirmation)
    return "write"


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

    if tier == "write" and not require_confirmation:
        return (
            f"This is a write operation that requires confirmation. "
            f"Please present the command to the user, explain what it will do, "
            f"and call again with require_confirmation=True after getting approval. "
            f"Command: {command}"
        )

    # 4. Auto-append --output json if not specified
    if "--output" not in command:
        command = f"{command} --output json"

    # 5. Execute
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

    # 6. Return output (truncated)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if len(stderr) > MAX_OUTPUT_CHARS:
            stderr = stderr[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
        return f"Error (exit code {result.returncode}): {stderr}"

    output = result.stdout.strip()
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"

    return output if output else "(no output)"
