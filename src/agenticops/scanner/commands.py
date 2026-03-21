"""Per-provider CLI command maps for resource discovery."""

# (parser_key, cli_command) — {region} is substituted at runtime
# Commands marked "global" run once, not per-region.

AWS_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "computing": [
        ("aws_ec2_instances", "aws ec2 describe-instances --region {region}"),
        ("aws_lambda_functions", "aws lambda list-functions --region {region}"),
        ("aws_ecs_clusters", "aws ecs list-clusters --region {region}"),
        ("aws_eks_clusters", "aws eks list-clusters --region {region}"),
        ("aws_autoscaling_groups", "aws autoscaling describe-auto-scaling-groups --region {region}"),
    ],
    "networking": [
        ("aws_vpcs", "aws ec2 describe-vpcs --region {region}"),
        ("aws_security_groups", "aws ec2 describe-security-groups --region {region}"),
        ("aws_load_balancers", "aws elbv2 describe-load-balancers --region {region}"),
        ("aws_subnets", "aws ec2 describe-subnets --region {region}"),
        ("aws_nat_gateways", "aws ec2 describe-nat-gateways --region {region}"),
        ("aws_route53_zones", "aws route53 list-hosted-zones"),  # global
    ],
    "databases": [
        ("aws_rds_instances", "aws rds describe-db-instances --region {region}"),
        ("aws_dynamodb_tables", "aws dynamodb list-tables --region {region}"),
        ("aws_elasticache", "aws elasticache describe-cache-clusters --region {region}"),
        ("aws_opensearch_domains", "aws opensearch list-domain-names --region {region}"),
    ],
    "storage": [
        ("aws_s3_buckets", "aws s3api list-buckets"),  # global
        ("aws_ebs_volumes", "aws ec2 describe-volumes --region {region}"),
        ("aws_efs_file_systems", "aws efs describe-file-systems --region {region}"),
    ],
    "security": [
        ("aws_iam_roles", "aws iam list-roles"),  # global
        ("aws_kms_keys", "aws kms list-keys --region {region}"),
    ],
}

# Global commands (no {region} placeholder) — run once, not per-region
AWS_GLOBAL_COMMANDS = {"aws_s3_buckets", "aws_iam_roles", "aws_route53_zones"}

PROVIDER_COMMANDS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "aws": AWS_COMMANDS,
    # "azure": AZURE_COMMANDS,  # add when needed
    # "gcp": GCP_COMMANDS,
    # "alicloud": ALICLOUD_COMMANDS,
}
