# IAM Security Assessment — Deep Dive

## Credential Report Analysis

The IAM credential report is the single most important artifact for IAM security posture.

```bash
# Generate and download
aws iam generate-credential-report
aws iam get-credential-report --query Content --output text | base64 -d > /tmp/cred-report.csv
```

### Key Columns to Audit

| Column | Red Flag | Severity |
|--------|----------|----------|
| `password_enabled` + `mfa_active=false` | Console access without MFA | HIGH |
| `access_key_1_active=true` + `access_key_1_last_used_date` > 90d | Stale active key | MEDIUM |
| `access_key_2_active=true` | Two active keys (why?) | LOW |
| `user=<root_account>` + `access_key_1_active=true` | Root has access keys | CRITICAL |
| `user=<root_account>` + `mfa_active=false` | Root without MFA | CRITICAL |
| `password_last_used` > 90d + `password_enabled=true` | Stale console user | MEDIUM |

### Automated Checks

```bash
# Users with console access but no MFA
aws iam list-users --query 'Users[].UserName' --output text | \
  xargs -I{} sh -c 'aws iam list-mfa-devices --user-name {} --query "MFADevices" --output text | \
  grep -q "." || echo "NO MFA: {}"'

# Users with multiple active access keys
aws iam list-users --query 'Users[].UserName' --output text | \
  xargs -I{} sh -c 'COUNT=$(aws iam list-access-keys --user-name {} \
  --query "length(AccessKeyMetadata[?Status==\`Active\`])" --output text); \
  [ "$COUNT" -gt 1 ] && echo "MULTI-KEY: {} ($COUNT keys)"'
```

## Policy Analysis

### Dangerous Policy Patterns

```json
// CRITICAL: Full admin access
{
  "Effect": "Allow",
  "Action": "*",
  "Resource": "*"
}

// HIGH: Service-level wildcard
{
  "Effect": "Allow",
  "Action": "s3:*",
  "Resource": "*"
}

// HIGH: PassRole without restriction (privilege escalation)
{
  "Effect": "Allow",
  "Action": "iam:PassRole",
  "Resource": "*"
}

// CRITICAL: Can create new admin users
{
  "Effect": "Allow",
  "Action": ["iam:CreateUser", "iam:AttachUserPolicy"],
  "Resource": "*"
}
```

### Privilege Escalation Paths

1. **iam:PassRole + lambda:CreateFunction** → attach admin role to Lambda → execute
2. **iam:PassRole + ec2:RunInstances** → launch instance with admin role
3. **iam:CreatePolicyVersion** → create new policy version with `*:*`
4. **iam:AttachUserPolicy / iam:AttachRolePolicy** → attach AdminAccess
5. **sts:AssumeRole** with broad trust → assume into more privileged role
6. **lambda:UpdateFunctionCode** on privileged Lambda → inject code

```bash
# Check for PassRole without resource restriction
aws iam list-policies --scope Local --query 'Policies[].Arn' --output text | \
  xargs -I{} aws iam get-policy-version --policy-arn {} \
  --version-id $(aws iam get-policy --policy-arn {} --query 'Policy.DefaultVersionId' --output text) \
  --query 'PolicyVersion.Document'
```

## IAM Access Analyzer

```bash
# List analyzers
aws accessanalyzer list-analyzers

# Get external access findings (resources shared outside account)
aws accessanalyzer list-findings --analyzer-arn ARN \
  --filter '{"status":{"eq":["ACTIVE"]}}'

# Common finding types:
# - S3 bucket with public policy
# - IAM role with cross-account trust
# - KMS key with cross-account access
# - Lambda function with resource-based policy
# - SQS queue with open access policy
```

## Service Control Policies (SCPs)

For multi-account setups (AWS Organizations):

```bash
# List SCPs
aws organizations list-policies --filter SERVICE_CONTROL_POLICY

# Recommended deny SCPs:
# 1. Deny disabling CloudTrail
# 2. Deny leaving organization
# 3. Deny disabling GuardDuty
# 4. Deny creating IAM users with console access (use SSO)
# 5. Deny unencrypted S3 uploads (deny PutObject without encryption header)
```

## Cross-Account Trust Audit

```bash
# List all roles and extract trust policies
aws iam list-roles --query 'Roles[].[RoleName,AssumeRolePolicyDocument]' --output json | \
  python3 -c "
import json, sys
roles = json.load(sys.stdin)
for name, trust in roles:
    for stmt in trust.get('Statement', []):
        principal = stmt.get('Principal', {})
        if isinstance(principal, str) and principal == '*':
            print(f'CRITICAL: {name} trusts EVERYONE')
        elif isinstance(principal, dict):
            aws = principal.get('AWS', [])
            if isinstance(aws, str): aws = [aws]
            for a in aws:
                if a == '*':
                    print(f'CRITICAL: {name} trusts EVERYONE')
                elif ':root' in a and 'Condition' not in stmt:
                    print(f'HIGH: {name} trusts {a} without conditions')
"
```
