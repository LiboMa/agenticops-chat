# EFS Mount Issues Deep Dive

## NFS4.1 Mount Options

### Standard NFS4 Mount

```bash
# Full mount command with recommended options
sudo mount -t nfs4 \
  -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport \
  fs-0123456789abcdef0.efs.us-east-1.amazonaws.com:/ /mnt/efs
```

Option explanations:
- `nfsvers=4.1`: NFSv4.1 (required for EFS, supports parallel NFS for better performance)
- `rsize=1048576`: maximum read buffer size in bytes (1 MiB, maximizes throughput)
- `wsize=1048576`: maximum write buffer size in bytes (1 MiB, maximizes throughput)
- `hard`: client retries NFS requests indefinitely until server responds (recommended for data integrity)
- `timeo=600`: retry timeout in deciseconds (60 seconds before retry)
- `retrans=2`: number of retries before hard-mount retry cycle
- `noresvport`: use non-reserved source port (important for reconnection after network interruption)

### Soft vs Hard Mount

- `hard` (recommended): retries indefinitely, process hangs until server responds
  - Data integrity guaranteed, but unresponsive server causes hung processes
  - Use with `timeo=600` to set reasonable retry interval
- `soft`: gives up after `retrans` retries, returns error to application
  - Risk of data corruption if write fails silently
  - Only use if application handles NFS errors gracefully

## EFS Mount Helper (amazon-efs-utils)

The mount helper simplifies mounting and adds TLS support:

```bash
# Install amazon-efs-utils
# Amazon Linux 2 / AL2023:
sudo yum install -y amazon-efs-utils

# Ubuntu:
sudo apt-get install -y amazon-efs-utils
# Or from source:
git clone https://github.com/aws/efs-utils
cd efs-utils && sudo ./build-deb.sh
sudo apt-get install -y ./build/amazon-efs-utils*.deb

# Simple mount
sudo mount -t efs fs-0123456789abcdef0:/ /mnt/efs

# Mount with TLS (encryption in transit)
sudo mount -t efs -o tls fs-0123456789abcdef0:/ /mnt/efs

# Mount with access point
sudo mount -t efs -o tls,accesspoint=fsap-0123456789abcdef0 fs-0123456789abcdef0:/ /mnt/app

# Mount with IAM authorization
sudo mount -t efs -o tls,iam fs-0123456789abcdef0:/ /mnt/efs
```

The mount helper:
- Handles DNS resolution and mount target selection
- Manages stunnel for TLS encryption
- Supports IAM authorization
- Handles watchdog for connection monitoring
- Logs to `/var/log/amazon/efs/mount.log`

### Persistent Mount (fstab)

```bash
# Add to /etc/fstab for mount on boot
# Standard NFS:
fs-0123456789abcdef0.efs.us-east-1.amazonaws.com:/ /mnt/efs nfs4 \
  nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport,_netdev 0 0

# Using mount helper:
fs-0123456789abcdef0:/ /mnt/efs efs _netdev,tls 0 0

# With access point:
fs-0123456789abcdef0:/ /mnt/app efs _netdev,tls,accesspoint=fsap-0123456789abcdef0 0 0
```

`_netdev` is critical: tells the system to wait for network before mounting, preventing
boot failures if EFS is unreachable.

## TLS Encryption in Transit

EFS supports encryption in transit using TLS 1.2:

```bash
# Mount with TLS using mount helper
sudo mount -t efs -o tls fs-0123456789abcdef0:/ /mnt/efs

# Verify TLS is active
ps aux | grep stunnel
# Should show stunnel4 process handling the TLS tunnel

# Check stunnel logs
cat /var/log/amazon/efs/stunnel.log

# TLS troubleshooting:
# 1. Ensure amazon-efs-utils is installed and up to date
# 2. Check stunnel is installed: which stunnel4 || which stunnel
# 3. Verify certificate: openssl s_client -connect FS_ID.efs.REGION.amazonaws.com:2049
# 4. Check port 2049 is open in security group
```

The mount helper uses stunnel to create a TLS tunnel:
- Client connects to local stunnel on 127.0.0.1:PORT
- stunnel encrypts traffic and forwards to EFS on port 2049
- No application changes needed

## IAM Authorization

Control access to EFS file systems using IAM policies:

```bash
# Mount with IAM authorization
sudo mount -t efs -o tls,iam fs-0123456789abcdef0:/ /mnt/efs

# Required IAM permissions on the instance role:
```

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientWrite",
      "elasticfilesystem:ClientRootAccess"
    ],
    "Resource": "arn:aws:elasticfilesystem:us-east-1:123456789012:file-system/fs-0123456789abcdef0",
    "Condition": {
      "Bool": {
        "elasticfilesystem:AccessedViaMountTarget": "true"
      }
    }
  }]
}
```

```bash
# EFS file system policy (resource policy on the file system itself)
aws efs put-file-system-policy --file-system-id fs-0123456789abcdef0 \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Sid": "EnforceTLS",
      "Effect": "Deny",
      "Principal": {"AWS": "*"},
      "Action": "*",
      "Condition": {
        "Bool": {"aws:SecureTransport": "false"}
      }
    }, {
      "Sid": "AllowAppRole",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::123456789012:role/app-role"},
      "Action": ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"],
      "Condition": {
        "Bool": {"elasticfilesystem:AccessedViaMountTarget": "true"}
      }
    }]
  }'
```

## Access Points

Access points provide application-specific entry points with enforced user identity and root directory:

```bash
# Create access point
aws efs create-access-point --file-system-id fs-0123456789abcdef0 \
  --posix-user '{"Uid": 1000, "Gid": 1000}' \
  --root-directory '{
    "Path": "/app/data",
    "CreationInfo": {
      "OwnerUid": 1000,
      "OwnerGid": 1000,
      "Permissions": "755"
    }
  }' \
  --tags Key=Name,Value=app-data-ap

# Mount using access point
sudo mount -t efs -o tls,accesspoint=fsap-0123456789abcdef0 \
  fs-0123456789abcdef0:/ /mnt/app-data
```

Access point use cases:
- **Multi-tenant isolation**: each app/team gets their own access point with chroot
- **Enforced user identity**: all operations appear as the configured POSIX user
- **Lambda integration**: Lambda functions mount EFS via access points
- **Container integration**: ECS/EKS mount EFS via access points per service

For EKS:

```yaml
# StorageClass for EFS with access point
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs-sc
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: fs-0123456789abcdef0
  directoryPerms: "700"
  uid: "1000"
  gid: "1000"
```

## Performance Mode Selection

### General Purpose (default, recommended for most workloads)

- Lower latency (sub-millisecond for metadata operations)
- Up to 55,000 read IOPS and 25,000 write IOPS (per file system)
- Sufficient for web serving, content management, home directories, development
- Can monitor `PercentIOLimit` metric -- if consistently > 95%, consider Max I/O

### Max I/O (legacy, for highly parallelized workloads)

- Higher aggregate throughput and IOPS
- Slightly higher latency on metadata operations
- Use for: big data analytics, media processing, genomics, with hundreds of instances
- Note: General Purpose mode has been significantly improved and now handles most workloads

```bash
# Check current performance mode (cannot change after creation)
aws efs describe-file-systems --file-system-id fs-0123456789abcdef0 \
  --query 'FileSystems[].PerformanceMode'

# Must create new file system to change performance mode
aws efs create-file-system --performance-mode maxIO \
  --throughput-mode elastic --encrypted
```

## Throughput Mode Comparison

| Mode | Baseline | Burst | Max | Cost |
|------|----------|-------|-----|------|
| Bursting | 50 MiB/s per TiB | 100 MiB/s per TiB (min 100 MiB/s) | Depends on size | Included |
| Provisioned | Specified | N/A | 3 GiB/s read, 1 GiB/s write | Per MiB/s above bursting |
| Elastic | Auto | Auto | 10 GiB/s read, 3 GiB/s write | Per GiB transferred |

```bash
# Switch throughput mode (can change anytime)
# To Provisioned:
aws efs update-file-system --file-system-id fs-0123456789abcdef0 \
  --throughput-mode provisioned --provisioned-throughput-in-mibps 256

# To Elastic:
aws efs update-file-system --file-system-id fs-0123456789abcdef0 \
  --throughput-mode elastic

# To Bursting:
aws efs update-file-system --file-system-id fs-0123456789abcdef0 \
  --throughput-mode bursting
```

## Connection Troubleshooting

### Network Connectivity Checks

```bash
# 1. Verify mount target exists in your AZ
aws efs describe-mount-targets --file-system-id fs-0123456789abcdef0 \
  --query 'MountTargets[].{AZ:AvailabilityZoneName,IP:IpAddress,SubnetId:SubnetId,State:LifeCycleState}'

# 2. Test DNS resolution
nslookup fs-0123456789abcdef0.efs.us-east-1.amazonaws.com
# Should resolve to mount target IP in your AZ

# 3. Test TCP connectivity to port 2049
telnet fs-0123456789abcdef0.efs.us-east-1.amazonaws.com 2049
# Or:
nc -zv fs-0123456789abcdef0.efs.us-east-1.amazonaws.com 2049

# 4. Check security group on mount target
aws efs describe-mount-targets --file-system-id fs-0123456789abcdef0 \
  --query 'MountTargets[].MountTargetId' --output text | \
  xargs -I {} aws efs describe-mount-target-security-groups --mount-target-id {}

# 5. Verify security group allows NFS
aws ec2 describe-security-groups --group-ids sg-xxx \
  --query 'SecurityGroups[].IpPermissions[?FromPort==`2049`]'
```

### NFS Statistics

```bash
# Check NFS client statistics
nfsstat -c
# Shows RPC and NFS operation counts, retransmissions

# Detailed per-mount statistics
cat /proc/self/mountstats
# Or use mountstats tool:
mountstats /mnt/efs
# Shows: ops/second, RTT (round-trip time), execute time, bytes transferred

# Monitor NFS operations in real-time
nfsiostat 5
# Updates every 5 seconds: ops/s, kB/s, kB/op, retrans, avg RTT, avg exe
```

### Common Mount Failures and Fixes

**"mount.nfs: Connection timed out"**
- Security group not allowing port 2049
- No route from instance subnet to mount target subnet
- NACL blocking NFS traffic
- Mount target not in instance's AZ

**"mount.nfs: access denied by server"**
- EFS file system policy denying the request
- IAM authorization required but not configured
- Access point UID/GID mismatch

**"mount.nfs: No such device"**
- NFS kernel module not loaded: `sudo modprobe nfs`
- nfs-utils / nfs-common not installed

**"mount.nfs: Network is unreachable"**
- No mount target in the AZ
- VPC DNS resolution not enabled
- Instance in different VPC than mount target

## Backup Strategies

### AWS Backup (recommended)

```bash
# Create backup plan for EFS
aws backup create-backup-plan --backup-plan '{
  "BackupPlanName": "efs-daily",
  "Rules": [{
    "RuleName": "DailyBackup",
    "TargetBackupVaultName": "Default",
    "ScheduleExpression": "cron(0 5 ? * * *)",
    "StartWindowMinutes": 60,
    "CompletionWindowMinutes": 180,
    "Lifecycle": {
      "MoveToColdStorageAfterDays": 30,
      "DeleteAfterDays": 365
    }
  }]
}'

# Assign EFS file system to backup plan
aws backup create-backup-selection --backup-plan-id PLAN_ID \
  --backup-selection '{
    "SelectionName": "efs-resources",
    "IamRoleArn": "arn:aws:iam::123456789012:role/aws-backup-role",
    "Resources": ["arn:aws:elasticfilesystem:us-east-1:123456789012:file-system/fs-0123456789abcdef0"]
  }'
```

### EFS-to-EFS Replication

```bash
# Create replication configuration (cross-region DR)
aws efs create-replication-configuration \
  --source-file-system-id fs-0123456789abcdef0 \
  --destinations '[{
    "Region": "us-west-2",
    "AvailabilityZoneName": "",
    "KmsKeyId": ""
  }]'

# Check replication status
aws efs describe-replication-configurations \
  --file-system-id fs-0123456789abcdef0

# RPO: most changes replicated within 15 minutes (best-effort)
# Destination is read-only until you delete the replication configuration
```

### EFS Data Sync

For larger migrations or scheduled sync to/from EFS:

```bash
# Create DataSync task: on-prem NFS to EFS
aws datasync create-task \
  --source-location-arn arn:aws:datasync:us-east-1:123456789012:location/loc-source \
  --destination-location-arn arn:aws:datasync:us-east-1:123456789012:location/loc-efs \
  --options '{
    "VerifyMode": "ONLY_FILES_TRANSFERRED",
    "OverwriteMode": "ALWAYS",
    "Atime": "BEST_EFFORT",
    "Mtime": "PRESERVE",
    "PreserveDeletedFiles": "REMOVE",
    "TransferMode": "CHANGED"
  }'

# Execute task
aws datasync start-task-execution --task-arn TASK_ARN
```
