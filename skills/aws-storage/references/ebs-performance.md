# EBS Performance Deep Dive

## Volume Types Comparison

| Feature | gp3 | gp2 | io2 | io2 BE | st1 | sc1 |
|---------|-----|-----|-----|--------|-----|-----|
| Type | SSD | SSD | SSD | SSD | HDD | HDD |
| Size | 1 GiB-16 TiB | 1 GiB-16 TiB | 4 GiB-16 TiB | 4 GiB-64 TiB | 125 GiB-16 TiB | 125 GiB-16 TiB |
| Max IOPS | 16,000 | 16,000 | 64,000 | 256,000 | 500 | 250 |
| Max Throughput | 1,000 MiB/s | 250 MiB/s | 1,000 MiB/s | 4,000 MiB/s | 500 MiB/s | 250 MiB/s |
| Baseline IOPS | 3,000 | 3/GiB | Provisioned | Provisioned | N/A | N/A |
| Burst | N/A | 3,000 | N/A | N/A | 250 MiB/s/TiB | 80 MiB/s/TiB |
| Durability | 99.8-99.9% | 99.8-99.9% | 99.999% | 99.999% | 99.8-99.9% | 99.8-99.9% |
| Multi-Attach | No | No | Yes | Yes | No | No |
| Boot volume | Yes | Yes | Yes | Yes | No | No |

## IOPS Calculations

### gp2 IOPS Formula

```
baseline_iops = min(16000, max(100, 3 * volume_size_gb))
```

Examples:
- 10 GB volume: max(100, 30) = 100 IOPS baseline, can burst to 3000
- 100 GB volume: max(100, 300) = 300 IOPS baseline, can burst to 3000
- 1000 GB volume: min(16000, 3000) = 3000 IOPS (no burst needed, equals burst)
- 5334 GB volume: min(16000, 16002) = 16000 IOPS (max, no bursting)

### gp2 Burst Credits

```
Initial credits: 5,400,000 I/O credits
Credit earn rate: baseline IOPS per second (e.g., 300 for 100 GB)
Credit spend rate: actual IOPS consumed per second
Burst rate: up to 3000 IOPS (if credits available)

Time to deplete (bursting at 3000 from 300 baseline):
5,400,000 / (3000 - 300) = 2000 seconds = ~33 minutes

Time to refill from zero:
5,400,000 / 300 = 18,000 seconds = ~5 hours
```

### gp3 IOPS and Throughput

gp3 decouples IOPS and throughput from volume size:

```bash
# Create gp3 with custom IOPS and throughput
aws ec2 create-volume --volume-type gp3 --size 100 \
  --iops 6000 --throughput 400 \
  --availability-zone us-east-1a

# Modify existing volume
aws ec2 modify-volume --volume-id vol-0123456789abcdef0 \
  --volume-type gp3 --iops 10000 --throughput 700

# Check modification status
aws ec2 describe-volumes-modifications --volume-ids vol-0123456789abcdef0
```

Pricing (gp3):
- Storage: $0.08/GB-month
- IOPS above 3000: $0.005/IOPS-month
- Throughput above 125 MiB/s: $0.040/MiB/s-month
- Example: 500 GB, 6000 IOPS, 400 MiB/s = $40 + $15 + $11 = $66/month

## Throughput Calculations

Maximum throughput depends on both volume type AND I/O size:

```
Throughput = IOPS * I/O_size

For gp3 at 3000 IOPS:
- 16 KiB I/O: 3000 * 16 KiB = 46.9 MiB/s
- 256 KiB I/O: 3000 * 256 KiB = 750 MiB/s (capped at 125 MiB/s baseline)

For io2 at 64000 IOPS:
- 16 KiB I/O: 64000 * 16 KiB = 1000 MiB/s (at the max)
- Larger I/O sizes don't help if throughput is already at volume max
```

Optimal I/O size depends on workload:
- Databases (random): 16 KiB (PostgreSQL), 16-64 KiB (MySQL)
- Sequential (logs, streaming): 256 KiB - 1 MiB
- Larger I/O means fewer IOPS needed for same throughput

## Multi-Attach (io2 only)

Share a single io2 volume across up to 16 Nitro instances in the same AZ:

```bash
aws ec2 create-volume --volume-type io2 --size 500 --iops 32000 \
  --availability-zone us-east-1a --multi-attach-enabled

# Attach to multiple instances
aws ec2 attach-volume --volume-id vol-xxx --instance-id i-aaa --device /dev/sdf
aws ec2 attach-volume --volume-id vol-xxx --instance-id i-bbb --device /dev/sdf
```

Requirements:
- Must use a cluster-aware file system (GFS2, OCFS2) or handle coordination in app
- NOT ext4 or xfs (these are not cluster-aware and will corrupt data)
- Same Availability Zone only
- io2 or io2 Block Express only

Use cases: clustered databases, shared application state, Oracle RAC

## EBS-Optimized Instance Throughput Limits

Each instance type has a maximum EBS bandwidth that caps ALL attached volumes combined:

```bash
# Check EBS limits for instance type
aws ec2 describe-instance-types --instance-types m7g.xlarge \
  --query 'InstanceTypes[].EbsInfo.{
    Optimized: EbsOptimizedSupport,
    MaxBandwidthMbps: EbsOptimizedInfo.MaximumBandwidthInMbps,
    MaxIOPS: EbsOptimizedInfo.MaximumIops,
    MaxThroughputMBps: EbsOptimizedInfo.MaximumThroughputInMBps
  }'
```

Example instance EBS limits:

| Instance Type | Max Bandwidth | Max IOPS | Max Throughput |
|--------------|--------------|----------|---------------|
| m7g.medium | 2,500 Mbps | 11,000 | 312.5 MiB/s |
| m7g.xlarge | 5,000 Mbps | 22,000 | 625 MiB/s |
| m7g.4xlarge | 10,000 Mbps | 40,000 | 1,250 MiB/s |
| m7g.16xlarge | 20,000 Mbps | 80,000 | 2,500 MiB/s |
| i4i.large | 10,000 Mbps | 40,000 | 1,250 MiB/s |

If your volumes can do more IOPS/throughput than the instance allows,
the instance becomes the bottleneck. Upgrade instance type or distribute
I/O across multiple instances.

## Striped RAID 0

Combine multiple EBS volumes for higher throughput and IOPS:

```bash
# Create 4 gp3 volumes at 4000 IOPS each = 16000 IOPS total
for i in 1 2 3 4; do
  aws ec2 create-volume --volume-type gp3 --size 250 --iops 4000 \
    --throughput 250 --availability-zone us-east-1a
done

# On the instance: create RAID 0 with mdadm
sudo mdadm --create /dev/md0 --level=0 --raid-devices=4 \
  /dev/nvme1n1 /dev/nvme2n1 /dev/nvme3n1 /dev/nvme4n1

sudo mkfs.xfs /dev/md0
sudo mkdir /mnt/raid
sudo mount /dev/md0 /mnt/raid

# Persist across reboots
sudo mdadm --detail --scan >> /etc/mdadm.conf
# Add to /etc/fstab
```

RAID 0 aggregates:
- IOPS: sum of all volumes
- Throughput: sum of all volumes (up to instance EBS limit)
- Capacity: sum of all volumes
- Risk: ANY volume failure loses ALL data (no redundancy)

Use RAID 0 for: temporary data, reproducible data, replicated databases.
Do NOT use for: single-copy data without backups.

## CloudWatch Metrics Interpretation

```bash
# Get EBS metrics for a volume
aws cloudwatch get-metric-statistics \
  --namespace AWS/EBS --metric-name VolumeQueueLength \
  --dimensions Name=VolumeId,Value=vol-0123456789abcdef0 \
  --start-time 2024-01-01T00:00:00Z --end-time 2024-01-01T01:00:00Z \
  --period 300 --statistics Average Maximum
```

### Key Metrics

**VolumeQueueLength** (most important for diagnosing bottlenecks):
- Average < 1: volume is keeping up with I/O demand
- Average 1-4: moderate queue, may see latency spikes
- Average > 4: significant bottleneck, upgrade volume or reduce I/O
- Sustained > 1: volume IOPS are insufficient for workload

**VolumeReadOps / VolumeWriteOps**:
- Divide by period to get IOPS: `VolumeReadOps / 300 = read IOPS (5-min avg)`
- Compare to volume baseline and provisioned IOPS
- If at volume max consistently, need to upgrade

**BurstBalance** (gp2 only):
- 100%: full credits, can burst
- Declining: sustained I/O above baseline
- 0%: no burst available, stuck at baseline
- Solution: migrate to gp3 with specified IOPS

**VolumeReadBytes / VolumeWriteBytes**:
- Divide by period for throughput: `VolumeReadBytes / 300 = read bytes/sec`
- Compare to volume max throughput
- Compare to instance EBS bandwidth limit

**VolumeTotalReadTime / VolumeTotalWriteTime**:
- Divide by ops for average latency: `VolumeTotalReadTime / VolumeReadOps = avg read latency`
- SSD targets: < 1ms typical, < 10ms acceptable
- HDD targets: < 20ms typical

## Migration Strategies

### gp2 to gp3

```bash
# Identify all gp2 volumes
aws ec2 describe-volumes --filters Name=volume-type,Values=gp2 \
  --query 'Volumes[].{VolumeId:VolumeId,Size:Size,IOPS:Iops,State:State}'

# Modify to gp3 (online, no downtime)
aws ec2 modify-volume --volume-id vol-0123456789abcdef0 \
  --volume-type gp3 --iops 3000 --throughput 125

# Check modification progress
aws ec2 describe-volumes-modifications --volume-ids vol-0123456789abcdef0

# States: modifying → optimizing → completed
# Optimizing: volume is usable but modification still processing
# Can only modify a volume once every 6 hours
```

Cost savings example:
- 500 GB gp2: $50/month (gets 1500 IOPS baseline)
- 500 GB gp3: $40/month (gets 3000 IOPS baseline, 125 MiB/s)
- Savings: 20% cheaper AND 2x the baseline IOPS

### standard (magnetic) to gp3

```bash
# Old magnetic volumes are significantly slower
aws ec2 describe-volumes --filters Name=volume-type,Values=standard \
  --query 'Volumes[].{VolumeId:VolumeId,Size:Size}'

# Migrate to gp3
aws ec2 modify-volume --volume-id vol-xxx --volume-type gp3
```

### When to use io2 instead of gp3

- Need > 16,000 IOPS per volume
- Need 99.999% durability (io2) vs 99.8-99.9% (gp2/gp3)
- Need Multi-Attach
- Need consistent sub-millisecond latency for databases
- Production databases with strict SLAs (Oracle, SQL Server, SAP HANA)

## Performance Testing

```bash
# Install fio (Flexible I/O Tester)
sudo yum install -y fio  # or apt-get install fio

# Test random read IOPS (16K block, queue depth 32)
sudo fio --name=randread --ioengine=libaio --iodepth=32 --rw=randread \
  --bs=16k --direct=1 --size=4G --numjobs=4 --runtime=60 \
  --group_reporting --filename=/dev/nvme1n1

# Test random write IOPS
sudo fio --name=randwrite --ioengine=libaio --iodepth=32 --rw=randwrite \
  --bs=16k --direct=1 --size=4G --numjobs=4 --runtime=60 \
  --group_reporting --filename=/dev/nvme1n1

# Test sequential throughput (256K block)
sudo fio --name=seqread --ioengine=libaio --iodepth=32 --rw=read \
  --bs=256k --direct=1 --size=4G --numjobs=4 --runtime=60 \
  --group_reporting --filename=/dev/nvme1n1

# Test mixed workload (70% read, 30% write)
sudo fio --name=mixed --ioengine=libaio --iodepth=32 --rw=randrw \
  --rwmixread=70 --bs=16k --direct=1 --size=4G --numjobs=4 --runtime=60 \
  --group_reporting --filename=/dev/nvme1n1
```

Always use `--direct=1` to bypass OS cache and test actual volume performance.
Use `--iodepth=32` or higher to fully saturate the volume queue.
Run for at least 60 seconds for stable results.
