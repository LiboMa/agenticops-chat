---
name: security-engineer
description: AWS security posture assessment and incident response — covers IAM analysis
  (overprivileged roles, unused credentials, MFA gaps), Security Hub findings, GuardDuty
  threats, Inspector vulnerabilities, S3 public access, SG/NACL misconfigurations,
  KMS key rotation, WAF rules, Config compliance, and CloudTrail integrity.
metadata:
  author: agenticops
  version: '1.0'
  domain: security
created_by: user
status: active
skill_version: '1.0'
created_at: '2026-07-10'
last_used: '2026-08-12'
---

# Security Engineer Skill

## Quick Decision Trees

### IAM Security Assessment

1. **Credential Hygiene**
   - `aws iam generate-credential-report` then `aws iam get-credential-report`
   - Check: password_enabled + mfa_active == false → MFA not enabled
   - Check: access_key_last_used > 90 days → stale access key
   - Check: password_last_used > 90 days → stale console user
   - Root account: must have MFA, should NOT have access keys

2. **Overprivileged Roles/Users**
   - `aws iam list-attached-user-policies --user-name USER`
   - `aws iam list-attached-role-policies --role-name ROLE`
   - Red flags: `AdministratorAccess`, `PowerUserAccess`, `*:*` in inline policies
   - `aws accessanalyzer list-findings --analyzer-arn ARN` → external access findings
   - Check service last accessed: `aws iam generate-service-last-accessed-details --arn ARN`

3. **Cross-Account Trust**
   - `aws iam list-roles --query 'Roles[?AssumeRolePolicyDocument]'`
   - Look for `Principal: {"AWS": "*"}` → anyone can assume
   - Look for `Condition` absence on cross-account trusts → no external ID protection

```
IAM Issue Detected
  |
  +-- Stale credentials (>90 days)?
  |     +-- Access key → disable/rotate key
  |     +-- Console password → force reset
  |
  +-- Overprivileged?
  |     +-- Admin policy on user → move to role, scope down
  |     +-- Wildcard (*:*) → replace with least-privilege
  |
  +-- No MFA?
  |     +-- Root → CRITICAL, enable hardware MFA immediately
  |     +-- User → HIGH, enforce MFA via policy condition
  |
  +-- Cross-account trust too broad?
        +-- Principal: * → restrict to specific account IDs
        +-- No ExternalId → add condition for ExternalId
```

### Security Hub Findings Triage

1. `aws securityhub get-findings --filters '{"RecordState":[{"Value":"ACTIVE","Comparison":"EQUALS"}],"SeverityLabel":[{"Value":"CRITICAL","Comparison":"EQUALS"}]}'`
2. Group by `GeneratorId` (rule source: CIS, PCI-DSS, Best Practices)
3. Priority: CRITICAL → HIGH → MEDIUM (ignore INFORMATIONAL for triage)

**Top CIS Benchmark Failures:**
| Control | Impact | Quick Fix |
|---------|--------|-----------|
| 1.4 Root MFA | CRITICAL | Enable hardware MFA on root |
| 1.10 MFA for console | HIGH | IAM policy with `aws:MultiFactorAuthPresent` |
| 2.1 CloudTrail enabled | CRITICAL | Enable multi-region trail |
| 2.6 S3 access logging | MEDIUM | Enable server access logging |
| 2.9 VPC flow logs | HIGH | Enable flow logs per VPC |
| 3.x CloudTrail alarm filters | MEDIUM | CloudWatch log metric filters |
| 4.1-4.3 SG open ports | HIGH | Restrict 0.0.0.0/0 ingress |

### GuardDuty Threat Assessment

1. `aws guardduty list-detectors` → get detector ID
2. `aws guardduty list-findings --detector-id DID --finding-criteria '{"Criterion":{"severity":{"Gte":7}}}'`
3. `aws guardduty get-findings --detector-id DID --finding-ids [IDs]`

**Finding Type Categories:**
| Prefix | Category | Typical Severity |
|--------|----------|-----------------|
| `Recon:` | Reconnaissance (port scan, API enum) | MEDIUM |
| `UnauthorizedAccess:` | Credential abuse, unusual API | HIGH-CRITICAL |
| `Trojan:` / `Backdoor:` | Malware indicators | CRITICAL |
| `CryptoCurrency:` | Crypto mining | HIGH |
| `Exfiltration:` | Data exfiltration patterns | CRITICAL |
| `Impact:` | Resource abuse (DoS, mining) | HIGH |
| `CredentialAccess:` | Credential compromise | CRITICAL |

```
GuardDuty Finding
  |
  +-- Severity >= 8 (CRITICAL)?
  |     +-- UnauthorizedAccess:IAMUser → rotate creds NOW, check CloudTrail
  |     +-- Trojan/Backdoor → isolate instance, forensic snapshot
  |     +-- CryptoCurrency → terminate instance, audit IAM
  |
  +-- Severity 4-7 (HIGH/MEDIUM)?
  |     +-- Recon → check SG rules, enable VPC flow logs
  |     +-- UnauthorizedAccess:EC2 → check instance profile, SSM access
  |
  +-- Severity < 4 (LOW)?
        +-- Usually informational → review weekly
```

### Inspector Vulnerability Assessment

1. `aws inspector2 list-findings --filter-criteria '{"findingStatus":[{"comparison":"EQUALS","value":"ACTIVE"}],"severity":[{"comparison":"EQUALS","value":"CRITICAL"}]}'`
2. Group by: EC2 instance / ECR image / Lambda function
3. Check: CVSS score, exploit availability, network reachability

**Priority Matrix:**
| CVSS | Network Reachable | Exploit Available | Priority |
|------|-------------------|-------------------|----------|
| ≥9.0 | Yes | Yes | P0 — patch NOW |
| ≥9.0 | No | Yes | P1 — patch this sprint |
| ≥7.0 | Yes | Yes | P1 |
| ≥7.0 | No | No | P2 — plan patch |
| <7.0 | * | * | P3 — backlog |

### S3 Public Access Assessment

1. `aws s3api get-public-access-block --bucket BUCKET` → check all 4 flags
2. `aws s3api get-bucket-policy --bucket BUCKET` → check for `"Principal": "*"`
3. `aws s3api get-bucket-acl --bucket BUCKET` → check for `AllUsers` or `AuthenticatedUsers`
4. Account-level: `aws s3control get-public-access-block --account-id ACCT`

```
S3 Public Access
  |
  +-- Account-level block disabled?
  |     +-- CRITICAL → enable account-level public access block
  |
  +-- Bucket policy allows Principal: *?
  |     +-- With Condition (IP/VPC restriction) → MEDIUM, review restriction
  |     +-- Without Condition → CRITICAL, restrict immediately
  |
  +-- ACL grants AllUsers?
  |     +-- READ → HIGH, remove public read
  |     +-- WRITE → CRITICAL, remove immediately
  |
  +-- Bucket-level block disabled?
        +-- Enable all 4 block settings unless there's a documented exception
```

### Security Group / NACL Audit

1. `aws ec2 describe-security-groups --query 'SecurityGroups[?IpPermissions[?contains(IpRanges[].CidrIp, \`0.0.0.0/0\`)]]'`
2. Flag open ports: SSH (22), RDP (3389), database ports (3306, 5432, 1433, 27017, 6379)
3. `aws ec2 describe-network-acls --query 'NetworkAcls[?Entries[?RuleAction==\`allow\` && CidrBlock==\`0.0.0.0/0\`]]'`

**High-Risk Open Ports:**
| Port | Service | 0.0.0.0/0 Risk |
|------|---------|----------------|
| 22 | SSH | CRITICAL — brute force target |
| 3389 | RDP | CRITICAL — ransomware vector |
| 3306 | MySQL | CRITICAL — data exposure |
| 5432 | PostgreSQL | CRITICAL — data exposure |
| 6379 | Redis | CRITICAL — no auth by default |
| 27017 | MongoDB | CRITICAL — no auth by default |
| 9200 | Elasticsearch | HIGH — data exposure |
| 8080/8443 | App server | MEDIUM — depends on app |

### Encryption and Key Management

1. **KMS Key Rotation**
   - `aws kms list-keys` then `aws kms get-key-rotation-status --key-id KEY`
   - Annual rotation should be enabled for CMKs
   - `aws kms describe-key --key-id KEY` → check KeyState, Origin

2. **EBS Encryption**
   - `aws ec2 describe-volumes --query 'Volumes[?!Encrypted]'` → unencrypted volumes
   - `aws ec2 get-ebs-encryption-by-default` → check account default

3. **RDS Encryption**
   - `aws rds describe-db-instances --query 'DBInstances[?!StorageEncrypted]'` → unencrypted instances

4. **S3 Default Encryption**
   - `aws s3api get-bucket-encryption --bucket BUCKET`

### CloudTrail Integrity

1. `aws cloudtrail describe-trails` → ensure multi-region trail exists
2. `aws cloudtrail get-trail-status --name TRAIL` → check IsLogging == true
3. Log file validation: `aws cloudtrail get-trail --name TRAIL` → LogFileValidationEnabled
4. S3 bucket check: ensure trail bucket has MFA delete and versioning

### AWS Config Compliance

1. `aws configservice describe-compliance-by-config-rule`
2. `aws configservice get-compliance-details-by-config-rule --config-rule-name RULE`
3. Key rules to check: `s3-bucket-public-read-prohibited`, `iam-root-access-key-check`,
   `restricted-ssh`, `rds-storage-encrypted`, `cloudtrail-enabled`

## Common Patterns

### Quick Security Posture Overview

```bash
# Security Hub summary
aws securityhub get-findings --filters '{"RecordState":[{"Value":"ACTIVE","Comparison":"EQUALS"}]}' \
  --query 'Findings[].{Title:Title,Severity:Severity.Label,Resource:Resources[0].Id}' \
  --max-items 20

# GuardDuty high-severity findings
aws guardduty list-detectors --query 'DetectorIds[0]' --output text | \
  xargs -I{} aws guardduty list-findings --detector-id {} \
  --finding-criteria '{"Criterion":{"severity":{"Gte":7}}}' --max-results 10

# Open security groups (0.0.0.0/0 on sensitive ports)
aws ec2 describe-security-groups \
  --query 'SecurityGroups[?IpPermissions[?contains(IpRanges[].CidrIp, `0.0.0.0/0`) && (FromPort==`22` || FromPort==`3389` || FromPort==`3306` || FromPort==`5432`)]]' \
  --output table

# IAM credential report
aws iam generate-credential-report && sleep 5 && \
  aws iam get-credential-report --query Content --output text | base64 -d
```

### Incident Response Commands

```bash
# Isolate compromised EC2 instance (replace SG with empty one)
aws ec2 create-security-group --group-name quarantine --description "Incident quarantine" --vpc-id VPC
aws ec2 modify-instance-attribute --instance-id INSTANCE --groups sg-quarantine-id

# Disable compromised IAM user
aws iam update-login-profile --user-name USER --no-password-reset-required
aws iam list-access-keys --user-name USER
aws iam update-access-key --user-name USER --access-key-id KEY --status Inactive

# Create forensic snapshot before terminating instance
aws ec2 create-snapshot --volume-id VOL --description "Forensic snapshot - incident YYYY-MM-DD"
```

## Key Metrics

| Metric | Warning | Critical | Notes |
|--------|---------|----------|-------|
| IAM users without MFA | > 0 | Root without MFA | CIS 1.4, 1.10 |
| Access keys > 90 days | > 5 users | > 20% of users | CIS 1.3, 1.4 |
| Security Hub CRITICAL findings | > 0 | > 10 | Active critical findings |
| GuardDuty HIGH/CRITICAL | > 0 | > 5 | Active threat findings |
| Open SGs (0.0.0.0/0 on 22,3389) | > 0 | > 5 | Direct attack surface |
| Unencrypted EBS volumes | > 0 | > 10 | Data-at-rest compliance |
| S3 buckets with public access | > 0 | Any | Data exposure risk |
| CloudTrail logging disabled | > 0 | Multi-region trail missing | Audit trail |
| Inspector CRITICAL CVEs | > 0 | > 10 (network reachable) | Exploitable vulns |






