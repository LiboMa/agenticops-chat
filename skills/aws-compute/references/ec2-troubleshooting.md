# EC2 Troubleshooting Deep Dive

## Instance Type Families

### Compute Optimized (C-series)
- **C7g/C7gn**: Graviton3, best price-performance for compute-heavy workloads
- **C7i**: Intel Sapphire Rapids, AVX-512 for vectorized workloads
- **C7a**: AMD EPYC, good balance of price and compute
- Use cases: batch processing, HPC, gaming servers, ML inference, video encoding

### Memory Optimized (R/X-series)
- **R7g**: Graviton3, up to 512 GiB memory
- **R7iz**: Intel, highest memory-to-CPU ratio in R-series
- **X2idn/X2iedn**: up to 4 TiB memory, instance store NVMe
- Use cases: in-memory databases (Redis, Memcached), real-time big data analytics, SAP HANA

### Storage Optimized (I/D-series)
- **I4i**: Intel, high random I/O, NVMe instance store
- **D3/D3en**: HDD-based dense storage, up to 336 TB
- **Im4gn/Is4gen**: Graviton2, NVMe instance store
- Use cases: NoSQL databases (Cassandra, MongoDB), data warehousing, distributed file systems

### Accelerated Computing (P/G/Inf-series)
- **P5**: NVIDIA H100, 8 GPUs, 640 GB GPU memory, for LLM training
- **G5**: NVIDIA A10G, for ML inference and graphics
- **Inf2**: AWS Inferentia2, cost-effective ML inference
- **Trn1**: AWS Trainium, for ML training workloads

## EBS Volume Types

### General Purpose SSD (gp3)
- Baseline: 3000 IOPS, 125 MiB/s throughput (independent of size)
- Provisionable: up to 16000 IOPS, up to 1000 MiB/s
- Cost: ~$0.08/GB-month + IOPS/throughput above baseline
- Best for: boot volumes, dev/test, small-medium databases

### General Purpose SSD (gp2) -- previous generation
- IOPS: 3 per GB, burst to 3000 (for volumes < 1000 GB)
- Formula: `min(16000, max(100, 3 * volume_size_gb))`
- Burst credits: start at 5.4M I/O credits, replenish at baseline rate
- Migrate to gp3: same or better performance, often cheaper

### Provisioned IOPS SSD (io2/io2 Block Express)
- io2: up to 64000 IOPS, 1000 MiB/s, 99.999% durability
- io2 Block Express: up to 256000 IOPS, 4000 MiB/s (on Nitro instances)
- Multi-Attach: share io2 across up to 16 Nitro instances (same AZ)
- Best for: critical databases, latency-sensitive transactional workloads

### Throughput Optimized HDD (st1)
- Throughput: baseline 40 MiB/s per TB, burst 250 MiB/s per TB, max 500 MiB/s
- Cannot be boot volume
- Best for: big data, data warehouses, log processing

### Cold HDD (sc1)
- Throughput: baseline 12 MiB/s per TB, burst 80 MiB/s per TB, max 250 MiB/s
- Lowest cost per GB
- Best for: infrequently accessed data, archival

## Instance Store Volumes

Instance store provides temporary block-level storage physically attached to the host:

```bash
# List instance store volumes
lsblk
# NVMe instance store devices appear as /dev/nvme*n1

# Check if instance type has instance store
aws ec2 describe-instance-types --instance-types i3.xlarge \
  --query 'InstanceTypes[].InstanceStorageInfo'

# Format and mount
mkfs.xfs /dev/nvme1n1
mkdir -p /mnt/instance-store
mount /dev/nvme1n1 /mnt/instance-store
```

Data persistence rules:
- **Survives**: reboot
- **Lost on**: stop, terminate, hibernate, underlying disk failure, host maintenance
- Never use for data that must persist -- use EBS or S3

## Launch Template Parameters

```bash
# Create launch template with key parameters
aws ec2 create-launch-template --launch-template-name my-template \
  --launch-template-data '{
    "ImageId": "ami-0123456789abcdef0",
    "InstanceType": "m7g.xlarge",
    "KeyName": "my-key",
    "SecurityGroupIds": ["sg-0123456789abcdef0"],
    "BlockDeviceMappings": [{
      "DeviceName": "/dev/xvda",
      "Ebs": {
        "VolumeSize": 100,
        "VolumeType": "gp3",
        "Iops": 3000,
        "Throughput": 125,
        "Encrypted": true,
        "DeleteOnTermination": true
      }
    }],
    "MetadataOptions": {
      "HttpTokens": "required",
      "HttpPutResponseHopLimit": 2,
      "HttpEndpoint": "enabled",
      "InstanceMetadataTags": "enabled"
    },
    "Monitoring": {"Enabled": true},
    "TagSpecifications": [{
      "ResourceType": "instance",
      "Tags": [{"Key": "Environment", "Value": "production"}]
    }]
  }'
```

## User Data Debugging

User data scripts run once on first boot (by default) via cloud-init:

```bash
# Check cloud-init status
cloud-init status --long

# View cloud-init logs
cat /var/log/cloud-init.log        # detailed cloud-init log
cat /var/log/cloud-init-output.log # stdout/stderr of user data script

# Re-run user data (for debugging -- removes cloud-init semaphore)
rm -rf /var/lib/cloud/instances/*/sem/
cloud-init single --name scripts-user --frequency always

# Common user data issues:
# 1. Missing shebang: must start with #!/bin/bash (or #!/usr/bin/env python3)
# 2. Encoding: must be base64-encoded when using API/CLI
# 3. Size limit: 16 KB max (use S3 for larger scripts)
# 4. Permissions: runs as root, but environment is minimal
# 5. Network not ready: add 'sleep 10' or use cloud-init modules for dependencies
```

## Instance Metadata Service (IMDSv2)

IMDSv2 uses session-oriented requests to prevent SSRF attacks:

```bash
# Get session token (required for IMDSv2)
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

# Get instance identity
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/instance-id

# Get instance type
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/instance-type

# Get IAM role credentials
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/iam/security-credentials/ROLE_NAME

# Get instance tags (requires InstanceMetadataTags=enabled)
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/tags/instance/Environment

# Enforce IMDSv2 on existing instance
aws ec2 modify-instance-metadata-options --instance-id i-1234567890abcdef0 \
  --http-tokens required --http-put-response-hop-limit 2
```

## Placement Groups

```bash
# Create cluster placement group (low-latency, single AZ)
aws ec2 create-placement-group --group-name hpc-cluster \
  --strategy cluster

# Create spread placement group (max 7 instances per AZ)
aws ec2 create-placement-group --group-name ha-spread \
  --strategy spread --spread-level rack

# Create partition placement group (for HDFS, Cassandra, Kafka)
aws ec2 create-placement-group --group-name data-partition \
  --strategy partition --partition-count 7

# Launch into placement group
aws ec2 run-instances --placement "GroupName=hpc-cluster" \
  --instance-type c7gn.16xlarge --count 10 ...
```

Placement group rules:
- Cluster: same AZ, same rack, up to 10 Gbps between instances (with enhanced networking)
- Spread: each instance on distinct hardware, max 7 per AZ per group
- Partition: up to 7 partitions per AZ, instances in same partition may share hardware

## Dedicated Hosts and Instances

```bash
# Allocate a dedicated host
aws ec2 allocate-hosts --instance-type m7i.xlarge \
  --availability-zone us-east-1a --quantity 1 \
  --auto-placement on

# Launch on dedicated host
aws ec2 run-instances --instance-type m7i.xlarge \
  --placement "HostId=h-0123456789abcdef0" ...

# Dedicated instance (simpler, no host management)
aws ec2 run-instances --instance-type m7i.xlarge \
  --placement "Tenancy=dedicated" ...
```

Use cases: licensing (Windows Server, SQL Server, Oracle), compliance, hardware isolation

## Spot Instance Interruption Handling

```bash
# Check for interruption notice (2 minutes before termination)
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/spot/termination-time

# Best practices:
# 1. Use diverse instance types (capacity-optimized allocation strategy)
# 2. Use Spot Fleet or EC2 Auto Scaling with mixed instance types
# 3. Handle interruption: checkpoint work, drain connections, deregister from ELB
# 4. Use Spot placement score to find best Region/AZ:
aws ec2 get-spot-placement-scores --instance-types m7g.xlarge m7i.xlarge c7g.xlarge \
  --target-capacity 20 --region-names us-east-1 us-west-2

# Spot Fleet request with diversification
aws ec2 request-spot-fleet --spot-fleet-request-config '{
  "AllocationStrategy": "capacity-optimized",
  "TargetCapacity": 10,
  "LaunchTemplateConfigs": [{
    "LaunchTemplateSpecification": {
      "LaunchTemplateName": "my-template",
      "Version": "$Latest"
    },
    "Overrides": [
      {"InstanceType": "m7g.xlarge"},
      {"InstanceType": "m7i.xlarge"},
      {"InstanceType": "m6g.xlarge"},
      {"InstanceType": "c7g.xlarge"}
    ]
  }]
}'
```

## Troubleshooting Workflow Summary

```
Instance unreachable
  |
  +-- Check instance state (running?)
  |     +-- stopping/stopped: was it stopped by ASG, scheduled event, or user?
  |     +-- terminated: check CloudTrail for TerminateInstances API call
  |
  +-- Check status checks
  |     +-- System: stop/start (hardware migration)
  |     +-- Instance: console output, rescue instance
  |
  +-- Check networking
  |     +-- Security group rules
  |     +-- NACL rules (inbound + outbound)
  |     +-- Route table (IGW or NAT route)
  |     +-- Public IP / EIP
  |     +-- VPN / Direct Connect path
  |
  +-- Check OS level
        +-- Console output / screenshot
        +-- SSM Agent status
        +-- Disk full, kernel panic, firewall
```
