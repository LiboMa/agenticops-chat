# GuardDuty & Security Hub — Deep Dive

## GuardDuty Finding Investigation

### Finding Structure

```json
{
  "Type": "UnauthorizedAccess:IAMUser/ConsoleLoginSuccess.B",
  "Severity": 8,
  "Resource": {
    "ResourceType": "AccessKey",
    "AccessKeyDetails": {
      "UserName": "compromised-user",
      "AccessKeyId": "AKIA..."
    }
  },
  "Service": {
    "Action": {
      "ActionType": "AWS_API_CALL",
      "AwsApiCallAction": {
        "Api": "ConsoleLogin",
        "RemoteIpDetails": {
          "IpAddressV4": "1.2.3.4",
          "Country": {"CountryName": "..."},
          "GeoLocation": {"Lat": 0, "Lon": 0}
        }
      }
    }
  }
}
```

### Investigation Playbooks by Finding Type

#### UnauthorizedAccess:IAMUser (Severity 5-8)

```bash
# 1. Identify the compromised principal
aws guardduty get-findings --detector-id DID --finding-ids [FID] \
  --query 'Findings[0].Resource.AccessKeyDetails'

# 2. Check recent API activity
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=Username,AttributeValue=USER \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ) \
  --max-results 50

# 3. Check for persistence mechanisms created
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=Username,AttributeValue=USER \
  --query 'Events[?contains(EventName, `Create`) || contains(EventName, `Attach`) || contains(EventName, `Put`)]'

# 4. Disable credentials
aws iam update-access-key --user-name USER --access-key-id KEY --status Inactive
aws iam update-login-profile --user-name USER --no-password-reset-required
```

#### Recon:EC2/PortProbeUnprotectedPort (Severity 2-5)

```bash
# 1. Identify the probed instance and port
aws guardduty get-findings --detector-id DID --finding-ids [FID] \
  --query 'Findings[0].Resource.InstanceDetails'

# 2. Check security group rules
aws ec2 describe-instances --instance-ids INSTANCE \
  --query 'Reservations[].Instances[].SecurityGroups'

# 3. Review the open port — is it intentional?
# If not, restrict the security group immediately
```

#### CryptoCurrency:EC2/BitcoinTool.B (Severity 8)

```bash
# 1. IMMEDIATE: Isolate the instance
aws ec2 create-security-group --group-name quarantine-$(date +%s) \
  --description "Incident quarantine" --vpc-id VPC_ID
aws ec2 modify-instance-attribute --instance-id INSTANCE \
  --groups sg-quarantine-id

# 2. Create forensic snapshot
aws ec2 describe-instances --instance-ids INSTANCE \
  --query 'Reservations[].Instances[].BlockDeviceMappings[].Ebs.VolumeId' --output text | \
  xargs -I{} aws ec2 create-snapshot --volume-id {} --description "forensic-$(date +%Y%m%d)"

# 3. Check how the instance was compromised
# - Instance profile with excessive permissions?
# - Public IP + open ports?
# - Compromised application?
aws ec2 describe-instances --instance-ids INSTANCE \
  --query 'Reservations[].Instances[].[IamInstanceProfile.Arn,PublicIpAddress,SecurityGroups]'
```

### GuardDuty Management

```bash
# Enable GuardDuty (with all protection plans)
aws guardduty create-detector --enable \
  --data-sources '{"S3Logs":{"Enable":true},"Kubernetes":{"AuditLogs":{"Enable":true}},"MalwareProtection":{"ScanEc2InstanceWithFindings":{"EbsVolumes":true}}}'

# Check detector status and data sources
aws guardduty list-detectors --query 'DetectorIds[0]' --output text | \
  xargs -I{} aws guardduty get-detector --detector-id {}

# Export findings to S3 (for SIEM integration)
aws guardduty create-publishing-destination --detector-id DID \
  --destination-type S3 \
  --destination-properties '{"DestinationArn":"arn:aws:s3:::guardduty-findings-bucket"}'
```

## Security Hub

### Standards and Controls

```bash
# List enabled standards
aws securityhub get-enabled-standards

# Enable CIS AWS Foundations Benchmark
aws securityhub batch-enable-standards --standards-subscription-requests \
  '[{"StandardsArn":"arn:aws:securityhub:::ruleset/cis-aws-foundations-benchmark/v/1.4.0"}]'

# Get compliance summary
aws securityhub get-findings --filters '{"ComplianceStatus":[{"Value":"FAILED","Comparison":"EQUALS"}],"RecordState":[{"Value":"ACTIVE","Comparison":"EQUALS"}]}' \
  --query 'Findings | sort_by(@, &Severity.Normalized) | reverse(@) | [0:20].{Title:Title,Severity:Severity.Label,Standard:GeneratorId,Resource:Resources[0].Id}'
```

### Aggregating Findings

```bash
# Count findings by severity
aws securityhub get-findings \
  --filters '{"RecordState":[{"Value":"ACTIVE","Comparison":"EQUALS"}]}' \
  --query 'length(Findings[?Severity.Label==`CRITICAL`])' --output text

# Findings for a specific resource
aws securityhub get-findings \
  --filters '{"ResourceId":[{"Value":"RESOURCE_ARN","Comparison":"EQUALS"}],"RecordState":[{"Value":"ACTIVE","Comparison":"EQUALS"}]}'

# Suppress known false positives
aws securityhub batch-update-findings \
  --finding-identifiers '[{"Id":"FINDING_ID","ProductArn":"PRODUCT_ARN"}]' \
  --workflow '{"Status":"SUPPRESSED"}' \
  --note '{"Text":"Known false positive: ...","UpdatedBy":"security-team"}'
```

### Security Hub Integrations

Security Hub aggregates findings from:
- **GuardDuty** — threat detection
- **Inspector** — vulnerability scanning
- **Macie** — S3 data classification
- **IAM Access Analyzer** — external access
- **Firewall Manager** — WAF/SG compliance
- **Config** — resource compliance
- **Third-party**: Qualys, Rapid7, Tenable, CrowdStrike, etc.

All findings normalized to **AWS Security Finding Format (ASFF)**.
