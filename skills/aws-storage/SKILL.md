---
name: aws-storage
description: "AWS storage troubleshooting — covers S3 (access denied, replication, lifecycle), EBS (IOPS limits, burst credits, snapshots), EFS (mount issues, throughput modes, burst credits), and FSx. Includes decision trees for performance issues, access problems, and cost optimization."
metadata:
  author: agenticops
  version: "1.0"
  domain: storage
---

# AWS Storage Skill

## Quick Decision Trees

### S3 Access Denied

1. Check bucket policy: `aws s3api get-bucket-policy --bucket BUCKET`
2. Check IAM policy: does the principal have `s3:GetObject`/`s3:PutObject`?
3. Object ownership: if object uploaded by different account, ACL or bucket policy needed
   - Check bucket ownership controls: `aws s3api get-bucket-ownership-controls --bucket BUCKET`
   - With BucketOwnerEnforced: ACLs disabled, bucket owner always owns objects
4. Block Public Access settings: `aws s3api get-public-access-block --bucket BUCKET`
   - Account-level block: `aws s3control get-public-access-block --account-id ACCT`
   - Four independent settings: BlockPublicAcls, IgnorePublicAcls, BlockPublicPolicy, RestrictPublicBuckets
5. VPC Endpoint policy: if using gateway endpoint, check policy document
   - Default policy allows all S3 actions -- custom policies may restrict
6. KMS: if SSE-KMS, caller needs `kms:Decrypt` (read) and `kms:GenerateDataKey` (write) on the key
   - Cross-account KMS: key policy must explicitly grant access to the calling account
7. Requester Pays: if enabled, request must include `x-amz-request-payer: requester` header
8. Organization SCP: Service Control Policies may block S3 operations at the OU/account level
9. Use `aws sts get-caller-identity` to confirm the actual principal making the request
10. Check CloudTrail for the exact error: `errorCode`, `errorMessage`, `requestParameters`

### EBS Performance

1. Check volume type and baseline IOPS:
   - gp3: baseline 3000 IOPS, 125 MiB/s (independent of size, can provision up to 16000 IOPS / 1000 MiB/s)
   - gp2: 3 IOPS per GB, burst to 3000 for volumes under 1000 GB, max 16000 IOPS at 5334+ GB
   - io2: provisioned up to 64000 IOPS per volume, 1000 MiB/s
   - io2 Block Express: up to 256000 IOPS, 4000 MiB/s (Nitro instances only)
   - st1: throughput-optimized HDD, baseline 40 MiB/s per TB, burst 250 MiB/s per TB
   - sc1: cold HDD, baseline 12 MiB/s per TB, burst 80 MiB/s per TB
2. CloudWatch metrics to check:
   - `VolumeReadOps` / `VolumeWriteOps`: actual IOPS consumed
   - `VolumeQueueLength`: number of pending I/O requests
   - `BurstBalance`: percentage of burst I/O credits remaining (gp2 only)
   - `VolumeReadBytes` / `VolumeWriteBytes`: throughput consumed
   - `VolumeThroughputPercentage`: percentage of provisioned throughput consumed (io volumes)
3. **VolumeQueueLength > 1** sustained: IOPS bottleneck, volume cannot keep up
4. gp2 burst credits depleted (`BurstBalance` near 0): performance drops to baseline (3 IOPS/GB)
5. Instance EBS bandwidth limit: some instance types cap total EBS throughput
   - Check instance type limit: `aws ec2 describe-instance-types --instance-types TYPE --query 'InstanceTypes[].EbsInfo'`
6. Solution path:
   - Upgrade gp2 to gp3: specify exact IOPS and throughput independently of size
   - Use io2 for sustained high IOPS (>16000)
   - Use RAID 0 (striping) for throughput beyond single volume limits
   - Use larger instance type if hitting instance-level EBS bandwidth cap

### EFS Mount Issues

1. Check mount target exists: `aws efs describe-mount-targets --file-system-id FS_ID`
2. Mount target must exist in the instance's Availability Zone
3. Security group on mount target: NFS port 2049 inbound from instance's security group
4. DNS resolution: `nslookup FS_ID.efs.REGION.amazonaws.com`
   - Must resolve to mount target IP in the instance's AZ
   - VPC DNS resolution and DNS hostnames must be enabled
5. NFS utils installed:
   - Amazon Linux / RHEL: `sudo yum install -y nfs-utils`
   - Ubuntu / Debian: `sudo apt-get install -y nfs-common`
   - Amazon EFS utils (recommended): `sudo yum install -y amazon-efs-utils`
6. Mount command:
   ```
   # Standard NFS mount
   sudo mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 \
     FS_ID.efs.REGION.amazonaws.com:/ /mnt/efs

   # Using EFS mount helper (simpler, supports TLS)
   sudo mount -t efs FS_ID:/ /mnt/efs
   sudo mount -t efs -o tls FS_ID:/ /mnt/efs
   ```
7. EFS Access Points: pre-configured entry points with POSIX user/group and root directory
   ```
   sudo mount -t efs -o tls,accesspoint=fsap-0123456789abcdef0 FS_ID:/ /mnt/app
   ```

### EFS Performance

1. Check throughput mode: Bursting vs Provisioned vs Elastic
2. **Bursting mode** (default):
   - Baseline: 50 MiB/s per TiB of data stored (minimum 1 MiB/s for any size)
   - Burst: up to 100 MiB/s per TiB (minimum 100 MiB/s for any size)
   - `BurstCreditBalance` metric: if depleted, throttled to baseline throughput
   - For a 100 GB file system: baseline 5 MiB/s, can burst to 100 MiB/s
3. **Provisioned throughput mode**:
   - Set specific throughput regardless of file system size
   - Up to 3 GiB/s read, 1 GiB/s write (with General Purpose)
   - Pay for provisioned throughput above what bursting would provide
4. **Elastic throughput mode** (recommended for variable workloads):
   - Automatically scales throughput up and down based on demand
   - Up to 10 GiB/s read, 3 GiB/s write
   - Pay only for throughput consumed (no pre-provisioning)
   - Best for spiky or unpredictable workloads
5. Check `PermittedThroughput` vs `MeteredIOBytes` in CloudWatch
6. Performance mode:
   - **General Purpose** (default): lower latency, sufficient for most workloads
   - **Max I/O**: higher aggregate throughput, slightly higher latency, for highly parallelized workloads
   - General Purpose now supports up to 55000 read IOPS and 25000 write IOPS

### S3 Replication Issues

1. Check replication config: `aws s3api get-bucket-replication --bucket BUCKET`
2. **Replication not working**:
   - Source bucket versioning enabled? (required)
   - Destination bucket versioning enabled? (required)
   - IAM role has `s3:ReplicateObject`, `s3:ReplicateDelete`, `s3:ReplicateTags` on destination
   - IAM role has `s3:GetObjectVersionForReplication`, `s3:GetObjectVersionTagging` on source
   - KMS objects: role needs `kms:Decrypt` on source KMS key, `kms:Encrypt` on destination KMS key
   - Replication rule status is `Enabled`
3. Replication scope:
   - Only NEW objects are replicated (existing objects need S3 Batch Replication)
   - Delete markers optionally replicated (DeleteMarkerReplication setting)
   - Lifecycle actions are NOT replicated
   - Objects encrypted with SSE-C are NOT replicated
4. S3 Replication Time Control (S3 RTC):
   - SLA: 99.99% of objects replicated within 15 minutes
   - Replication metrics and notifications enabled
   - Additional cost but provides predictable replication time
5. Check replication metrics: `ReplicationLatency`, `OperationsPendingReplication`, `OperationsFailedReplication`

### S3 Performance Optimization

1. Request rate: 5500 GET/HEAD, 3500 PUT/COPY/POST/DELETE per second per prefix
2. **Multipart upload**: required for >5 GB, recommended for >100 MB
   ```
   aws s3 cp large-file.dat s3://bucket/key --expected-size 10737418240
   # Or with explicit multipart:
   aws s3api create-multipart-upload --bucket BUCKET --key KEY
   aws s3api upload-part --bucket BUCKET --key KEY --part-number 1 \
     --upload-id ID --body part1.dat
   aws s3api complete-multipart-upload ...
   ```
3. **S3 Transfer Acceleration**: uses CloudFront edge locations for faster uploads
   ```
   aws s3api put-bucket-accelerate-configuration --bucket BUCKET \
     --accelerate-configuration Status=Enabled
   # Use endpoint: BUCKET.s3-accelerate.amazonaws.com
   ```
4. **Byte-range fetches**: parallel GET of byte ranges for large objects
5. **S3 Select / Glacier Select**: query subset of data from object (CSV, JSON, Parquet)

## Common Patterns

### S3 Cost Optimization

- **Lifecycle rules**: transition objects through storage classes
  - Standard to Standard-IA: 30+ days (minimum 128 KB, 30-day minimum storage)
  - Standard-IA to One Zone-IA: if single-AZ durability acceptable
  - To Glacier Instant Retrieval: 90+ days, millisecond retrieval
  - To Glacier Flexible Retrieval: 90+ days, minutes-to-hours retrieval
  - To Glacier Deep Archive: 180+ days, 12-48 hour retrieval
  - To Intelligent-Tiering: for unpredictable access patterns
- **Intelligent-Tiering**: automatic tiering, no retrieval fees
  - Frequent (default), Infrequent (30 days), Archive Instant (90 days)
  - Optional: Archive (90-730 days), Deep Archive (180-730 days)
  - Monitoring fee per object, but no retrieval charges
- **Delete incomplete multipart uploads**: set AbortIncompleteMultipartUpload lifecycle rule
- **S3 Analytics**: Storage Class Analysis recommends transition to IA based on access patterns
- **S3 Storage Lens**: organization-wide storage visibility and recommendations
- **Requester Pays**: for shared data buckets where consumers should pay transfer costs

### EBS Snapshots

- **Incremental**: only changed blocks stored after first full snapshot
- **Cross-region copy** for disaster recovery:
  ```
  aws ec2 copy-snapshot --source-region us-east-1 \
    --source-snapshot-id snap-0123456789abcdef0 \
    --destination-region us-west-2 --encrypted
  ```
- **Fast Snapshot Restore (FSR)**: immediate full performance when creating volume from snapshot
  - Without FSR: gradual performance as blocks are lazily loaded from S3
  - Cost: per AZ per hour per snapshot
- **DLM (Data Lifecycle Manager)**: automated snapshot policies
  ```
  aws dlm create-lifecycle-policy --description "Daily snapshots" \
    --state ENABLED --execution-role-arn ROLE_ARN \
    --policy-details '{
      "PolicyType": "EBS_SNAPSHOT_MANAGEMENT",
      "ResourceTypes": ["VOLUME"],
      "TargetTags": [{"Key": "Backup", "Value": "true"}],
      "Schedules": [{
        "Name": "DailySnapshots",
        "CreateRule": {"Interval": 24, "IntervalUnit": "HOURS"},
        "RetainRule": {"Count": 7}
      }]
    }'
  ```
- **EBS Snapshots Archive**: move rarely-accessed snapshots to archive tier (75% cheaper, 24-72h restore)

### FSx Overview

- **FSx for Lustre**: high-performance parallel file system for HPC, ML, media processing
  - Integrates with S3: data lazy-loaded from S3, results written back
  - Scratch (temporary, higher throughput) vs Persistent (replication, durability)
- **FSx for NetApp ONTAP**: multi-protocol (NFS, SMB, iSCSI), data deduplication, compression
  - SnapMirror for cross-region replication
  - FlexClone for instant test copies
- **FSx for OpenZFS**: NFS, snapshots, clones, compression
  - Good for: Linux-based workloads migrating from on-prem ZFS
- **FSx for Windows File Server**: SMB, DFS, AD integration
  - Good for: Windows workloads, home directories, CMS
