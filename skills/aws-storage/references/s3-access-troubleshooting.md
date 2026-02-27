# S3 Access Troubleshooting Deep Dive

## Policy Evaluation Logic

AWS evaluates S3 access requests through a specific order of precedence:

```
1. Explicit DENY in any policy  →  ACCESS DENIED (always wins)
2. Organization SCP ALLOW check →  If SCP exists and no allow, DENIED
3. Resource-based policy ALLOW  →  If bucket policy allows, ACCESS GRANTED
   (for same-account, this is sufficient even without IAM allow)
4. IAM identity-based ALLOW     →  If IAM policy allows, ACCESS GRANTED
5. Default                      →  ACCESS DENIED (implicit deny)
```

Cross-account access requires BOTH:
- Bucket policy (or ACL) allowing the external principal
- IAM policy in the calling account allowing the S3 action

Same-account access requires EITHER:
- Bucket policy allowing the principal, OR
- IAM policy allowing the action on the resource

## Bucket Policy vs IAM Policy Interaction

### Same-Account Access

```json
// Bucket policy allowing specific IAM role
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowAppRole",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::123456789012:role/app-role"},
    "Action": ["s3:GetObject", "s3:PutObject"],
    "Resource": "arn:aws:s3:::my-bucket/*"
  }]
}

// IAM policy on the role (alternative to bucket policy for same-account)
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:PutObject"],
    "Resource": "arn:aws:s3:::my-bucket/*"
  }]
}
```

For same-account: either policy is sufficient. Both are not required.

### Cross-Account Access

```json
// Bucket policy in Account A (bucket owner)
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "CrossAccountAccess",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::999888777666:role/external-role"},
    "Action": ["s3:GetObject"],
    "Resource": "arn:aws:s3:::my-bucket/*"
  }]
}

// IAM policy in Account B (caller) -- ALSO required
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject"],
    "Resource": "arn:aws:s3:::my-bucket/*"
  }]
}
```

Cross-account: both policies are required. Missing either one results in AccessDenied.

## VPC Endpoint Policies

### Gateway Endpoint (S3 and DynamoDB)

```json
// VPC endpoint policy restricting access to specific bucket
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowSpecificBucket",
    "Effect": "Allow",
    "Principal": "*",
    "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::my-bucket",
      "arn:aws:s3:::my-bucket/*"
    ]
  }]
}
```

```bash
# Check endpoint policy
aws ec2 describe-vpc-endpoints --vpc-endpoint-ids vpce-0123456789abcdef0 \
  --query 'VpcEndpoints[].PolicyDocument'

# Bucket policy restricting access to only come through VPC endpoint
# (denies requests not from the endpoint)
```

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyNotFromVPCE",
    "Effect": "Deny",
    "Principal": "*",
    "Action": "s3:*",
    "Resource": ["arn:aws:s3:::my-bucket", "arn:aws:s3:::my-bucket/*"],
    "Condition": {
      "StringNotEquals": {
        "aws:sourceVpce": "vpce-0123456789abcdef0"
      }
    }
  }]
}
```

This pattern is common for restricting bucket access to only traffic from within the VPC.
If you see AccessDenied on requests from outside the VPC (e.g., CloudShell, local machine),
this condition is likely the cause.

## Presigned URLs

```bash
# Generate presigned URL for download (default 1 hour expiry)
aws s3 presign s3://my-bucket/my-file.pdf --expires-in 3600

# For upload (PUT), use the SDK:
```

```python
import boto3

s3 = boto3.client('s3')
url = s3.generate_presigned_url(
    'put_object',
    Params={'Bucket': 'my-bucket', 'Key': 'uploads/file.txt', 'ContentType': 'text/plain'},
    ExpiresIn=3600
)
```

Presigned URL troubleshooting:
- URL expired: check `X-Amz-Expires` parameter
- Credentials used to sign must still be valid at access time
- STS temporary credentials: URL cannot outlive the session
- IAM user credentials: URL can be up to 7 days
- If signer loses permissions, presigned URL stops working

## S3 Access Points

Simplify access management for shared buckets:

```bash
# Create access point
aws s3control create-access-point --account-id 123456789012 \
  --name my-app-ap --bucket my-bucket \
  --vpc-configuration VpcId=vpc-0123456789abcdef0

# Access point policy
aws s3control put-access-point-policy --account-id 123456789012 \
  --name my-app-ap --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::123456789012:role/my-app"},
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:us-east-1:123456789012:accesspoint/my-app-ap/object/*"
    }]
  }'

# Use access point ARN instead of bucket name
aws s3api get-object \
  --bucket arn:aws:s3:us-east-1:123456789012:accesspoint/my-app-ap \
  --key my-file.txt output.txt
```

Access points benefits:
- Each app gets its own access point with its own policy
- VPC-restricted access points for network isolation
- Simpler than a complex bucket policy with many conditions
- Delegate access management per team/application

## Object Lock

Prevents object deletion or overwrite for a retention period:

```bash
# Enable Object Lock (only on bucket creation)
aws s3api create-bucket --bucket locked-bucket \
  --object-lock-enabled-for-bucket

# Set default retention
aws s3api put-object-lock-configuration --bucket locked-bucket \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "GOVERNANCE",
        "Days": 90
      }
    }
  }'
```

Modes:
- **Governance**: users with `s3:BypassGovernanceRetention` can override
- **Compliance**: nobody can delete/override, not even root account, until retention expires
- **Legal Hold**: indefinite hold, independent of retention period

## Bucket Ownership Controls

```bash
# Check current setting
aws s3api get-bucket-ownership-controls --bucket my-bucket

# Set to BucketOwnerEnforced (recommended -- disables ACLs)
aws s3api put-bucket-ownership-controls --bucket my-bucket \
  --ownership-controls '{
    "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
  }'
```

Settings:
- **BucketOwnerEnforced**: ACLs disabled, bucket owner owns all objects (recommended)
- **BucketOwnerPreferred**: bucket owner owns objects written with `bucket-owner-full-control` ACL
- **ObjectWriter** (legacy): uploader owns the object, ACLs control access

## Access Logging for Audit

```bash
# Enable server access logging
aws s3api put-bucket-logging --bucket my-bucket --bucket-logging-status '{
  "LoggingEnabled": {
    "TargetBucket": "my-log-bucket",
    "TargetPrefix": "s3-access-logs/my-bucket/"
  }
}'

# Log format includes:
# Bucket owner, bucket name, time, remote IP, requester ARN,
# request ID, operation (REST.GET.OBJECT), key, HTTP status,
# error code, bytes sent, total time, referrer, user-agent, version ID
```

For real-time analysis, use CloudTrail S3 data events instead:

```bash
aws cloudtrail put-event-selectors --trail-name my-trail \
  --event-selectors '[{
    "ReadWriteType": "All",
    "IncludeManagementEvents": true,
    "DataResources": [{
      "Type": "AWS::S3::Object",
      "Values": ["arn:aws:s3:::my-bucket/"]
    }]
  }]'
```

## Debugging Workflow

```
AccessDenied on S3 request
  |
  +-- Identify the actual principal
  |     aws sts get-caller-identity
  |     (Are you who you think you are? Check assumed role, federation)
  |
  +-- Check CloudTrail
  |     Filter: eventName=GetObject, errorCode=AccessDenied
  |     Look at: userIdentity, requestParameters, errorMessage
  |
  +-- Check bucket policy
  |     aws s3api get-bucket-policy --bucket BUCKET
  |     Look for: explicit Deny, missing Allow, condition keys
  |
  +-- Check IAM policy
  |     aws iam get-role-policy / list-attached-role-policies
  |     Look for: s3:* actions, Resource ARN matches
  |
  +-- Check Block Public Access
  |     aws s3api get-public-access-block --bucket BUCKET
  |     aws s3control get-public-access-block --account-id ACCT
  |
  +-- Check encryption (KMS)
  |     aws s3api head-object --bucket BUCKET --key KEY
  |     If SSE-KMS: check kms:Decrypt permission on key
  |
  +-- Check VPC endpoint
  |     aws ec2 describe-vpc-endpoints
  |     Check endpoint policy and bucket policy source VPC conditions
  |
  +-- Check SCP
        aws organizations list-policies-for-target --target-id ACCT_ID
        Look for S3 Deny statements in attached SCPs
```
