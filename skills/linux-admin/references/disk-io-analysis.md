# Disk I/O Analysis Reference

## iostat Deep Dive

`iostat` is the primary tool for disk I/O performance analysis. Always use the extended format with zero-suppression:

```bash
iostat -xz 1 5    # extended stats, skip idle devices, 1s interval, 5 samples
```

### Column Reference

| Column | Full Name | Description | Warning Threshold |
|--------|-----------|-------------|-------------------|
| rrqm/s | Read requests merged/s | Adjacent read requests merged by I/O scheduler | Informational |
| wrqm/s | Write requests merged/s | Adjacent write requests merged | Informational |
| r/s | Reads/s | Completed read requests per second | Device-dependent |
| w/s | Writes/s | Completed write requests per second | Device-dependent |
| rMB/s | Read MB/s | Throughput for reads | Device-dependent |
| wMB/s | Write MB/s | Throughput for writes | Device-dependent |
| avgrq-sz | Avg request size (sectors) | Average I/O request size | Small = random I/O |
| avgqu-sz | Avg queue size | Average number of requests in device queue | > 1 means queuing |
| await | Average wait (ms) | Total time from request to completion | > 10ms for SSD, > 20ms for HDD |
| r_await | Read await (ms) | Read-specific wait time | Same as await |
| w_await | Write await (ms) | Write-specific wait time | Same as await |
| svctm | Service time (ms) | Deprecated but still shown — actual device service time | N/A (deprecated) |
| %util | Utilization | Percentage of time device was busy | > 80% indicates saturation |

### Interpreting iostat Output

**Scenario 1: Random I/O bottleneck**

```
Device   r/s    w/s   rMB/s  wMB/s  avgrq-sz  avgqu-sz  await  %util
xvda    2500   1500    10.0    6.0      8.0       12.5    3.1    98.5
```

Analysis: High IOPS (4000 total), small request size (8 sectors = 4KB), high queue depth (12.5), near 100% utilization. This is classic random I/O saturation. The device is at IOPS limit.

**Scenario 2: Sequential throughput bottleneck**

```
Device   r/s    w/s   rMB/s  wMB/s  avgrq-sz  avgqu-sz  await  %util
xvda      50    200     0.2   200.0   2048.0       4.2    16.8   95.0
```

Analysis: Low IOPS but large request sizes (2048 sectors = 1MB), high write throughput. Device is at throughput limit, not IOPS limit.

**Scenario 3: Queuing delay (undersized device)**

```
Device   r/s    w/s   rMB/s  wMB/s  avgrq-sz  avgqu-sz  await  %util
xvda     500    300     2.0    1.2     16.0       45.0   56.2    99.1
```

Analysis: Moderate IOPS, moderate request size, but very high queue depth (45) and high await (56ms). The device cannot keep up with the workload. Upgrade to higher IOPS tier.

## blktrace — Block Layer Tracing

For deep I/O analysis when `iostat` is insufficient:

```bash
# Trace block I/O for 10 seconds
blktrace -d /dev/xvda -o - | blkparse -i - > /tmp/blktrace.txt

# With timeout
timeout 10 blktrace -d /dev/xvda -o /tmp/trace

# Parse and summarize
blkparse -i /tmp/trace -d /tmp/trace.bin
btt -i /tmp/trace.bin -o /tmp/btt_results

# btt output includes:
# D2C — time from request dispatch to completion (device latency)
# Q2C — time from queue to completion (total I/O latency)
# Q2D — time from queue to dispatch (queuing delay)
```

### blktrace Event Types

| Event | Meaning |
|-------|---------|
| Q | Queued — I/O request enters block layer |
| G | Get request — request allocated from pool |
| M | Merged — request merged with existing |
| I | Inserted — request inserted into device queue |
| D | Dispatched — sent to device driver |
| C | Completed — device reports completion |

## Filesystem Cache Behavior

### Page Cache

The Linux page cache sits between applications and block devices:

```bash
# Check page cache size
cat /proc/meminfo | grep -E "^(Cached|Buffers|Dirty|Writeback)"
# Cached:    memory used for file data cache
# Buffers:   memory used for block device metadata
# Dirty:     modified pages not yet written to disk
# Writeback: dirty pages currently being written

# Watch dirty pages in real-time
watch -n 1 'cat /proc/meminfo | grep -E "Dirty|Writeback"'
```

### Dirty Page Writeback Tunables

```bash
# Current settings
sysctl vm.dirty_ratio              # % of total memory — hard limit, blocks writers
sysctl vm.dirty_background_ratio   # % of total memory — background writeback starts
sysctl vm.dirty_expire_centisecs   # age (centiseconds) before dirty page is eligible for writeback
sysctl vm.dirty_writeback_centisecs # interval (centiseconds) between writeback daemon wakeups

# Tune for database workloads (lower dirty limits, frequent flushes)
sysctl -w vm.dirty_ratio=10
sysctl -w vm.dirty_background_ratio=5
sysctl -w vm.dirty_expire_centisecs=500
sysctl -w vm.dirty_writeback_centisecs=100

# Tune for throughput workloads (higher dirty limits)
sysctl -w vm.dirty_ratio=40
sysctl -w vm.dirty_background_ratio=10
```

### Read-Ahead Tuning

```bash
# Check current read-ahead (in 512-byte sectors)
blockdev --getra /dev/xvda

# Set read-ahead (e.g., 256KB = 512 sectors)
blockdev --setra 512 /dev/xvda

# For sequential workloads (large files): increase to 2048+ sectors
# For random workloads (databases): decrease to 128-256 sectors
```

## EBS-Specific Guidance

### EBS Volume Types

| Type | Max IOPS | Max Throughput | Burst | Use Case |
|------|----------|----------------|-------|----------|
| gp3 | 16,000 | 1,000 MB/s | No (provisioned) | General purpose, most workloads |
| gp2 | 16,000 | 250 MB/s | Yes (credit-based) | Legacy, consider migrating to gp3 |
| io2 | 64,000 | 1,000 MB/s | No (provisioned) | Databases, latency-sensitive |
| io2 Block Express | 256,000 | 4,000 MB/s | No | Highest performance |
| st1 | 500 | 500 MB/s | Yes | Sequential reads (data lakes) |
| sc1 | 250 | 250 MB/s | Yes | Cold storage, infrequent access |

### gp3 Performance

```
Base: 3,000 IOPS + 125 MB/s (included in price)
Max:  16,000 IOPS + 1,000 MB/s (pay per provisioned)

Key relationship:
- IOPS and throughput are independently provisioned
- Throughput limited by: min(provisioned_throughput, IOPS * IO_size)
- For 16K IOPS with 256KB I/O: 16000 * 256KB = 4000 MB/s (capped at 1000 MB/s)
```

### gp2 Burst Credits

```bash
# Monitor via CloudWatch:
# VolumeQueueLength — requests waiting (should be < 1)
# BurstBalance — remaining burst credits (100% = full, 0% = depleted)
# VolumeReadOps / VolumeWriteOps — actual IOPS

# gp2 baseline: 3 IOPS per GB (minimum 100 IOPS)
# 100 GB gp2 = 300 baseline IOPS, can burst to 3000 IOPS
# 1000 GB gp2 = 3000 baseline IOPS (no burst needed, already at burst level)
# 5334+ GB gp2 = 16000 IOPS (max, no burst)
```

### EBS Optimization Checklist

```bash
# 1. Check if instance is EBS-optimized
aws ec2 describe-instances --instance-ids i-xxx \
  --query 'Reservations[].Instances[].EbsOptimized'

# 2. Check instance EBS bandwidth limit
# m5.xlarge = 4,750 Mbps = ~593 MB/s maximum aggregate EBS throughput
# Multiple volumes share this bandwidth

# 3. Monitor actual performance
# CloudWatch metrics: VolumeReadBytes, VolumeWriteBytes, VolumeReadOps, VolumeWriteOps

# 4. Check for micro-bursting
# 1-minute CloudWatch may hide 1-second spikes
# Use per-second iostat for host-side verification

# 5. NVMe timeout (Nitro instances)
cat /sys/module/nvme_core/parameters/io_timeout
# Default: 30 seconds — EBS I/O that takes longer will timeout
# For io2 volumes doing snapshot operations, this may need increasing
```

## fstrim and TRIM/Discard

TRIM tells SSDs/EBS which blocks are no longer in use, enabling garbage collection:

```bash
# One-time TRIM of a filesystem
fstrim -v /mount/point

# Check if TRIM is supported
lsblk -D    # DISC-GRAN and DISC-MAX should be non-zero

# Automatic TRIM options:
# Option 1: fstrim timer (recommended for EBS)
systemctl enable fstrim.timer
systemctl start fstrim.timer
# Runs weekly by default

# Option 2: mount with discard option (continuous TRIM)
# /etc/fstab: /dev/xvda1 / ext4 defaults,discard 0 1
# WARNING: continuous discard adds latency to every delete operation
# Weekly fstrim.timer is usually better for performance
```

## LVM Troubleshooting

### Common LVM Commands

```bash
# Physical volumes
pvs                     # summary
pvdisplay /dev/xvdb     # detailed

# Volume groups
vgs                     # summary
vgdisplay vg_data       # detailed

# Logical volumes
lvs                     # summary
lvdisplay /dev/vg_data/lv_app   # detailed

# Check free space
vgs -o +vg_free_count,vg_extent_count
```

### LVM Extend Workflow

```bash
# 1. Extend EBS volume in AWS console/CLI first
# 2. Rescan block device
echo 1 > /sys/block/xvdb/device/rescan     # for SCSI
partprobe                                     # for partitioned disks

# 3. Extend physical volume
pvresize /dev/xvdb

# 4. Extend logical volume
lvextend -l +100%FREE /dev/vg_data/lv_app
# Or by specific size:
lvextend -L +50G /dev/vg_data/lv_app

# 5. Resize filesystem
# ext4:
resize2fs /dev/vg_data/lv_app
# xfs (must be mounted):
xfs_growfs /mount/point
```

### LVM Snapshot for Backup

```bash
# Create snapshot (needs free PE in VG)
lvcreate -L 10G -s -n snap_backup /dev/vg_data/lv_app

# Mount snapshot read-only
mount -o ro /dev/vg_data/snap_backup /mnt/snapshot

# After backup, remove snapshot
lvremove /dev/vg_data/snap_backup

# WARNING: Snapshot performance degrades as it fills up
# Monitor: lvs -o +snap_percent
```

## I/O Scheduler Selection

```bash
# Check current scheduler
cat /sys/block/xvda/queue/scheduler
# Output: [mq-deadline] none kyber bfq

# Change scheduler
echo kyber > /sys/block/xvda/queue/scheduler

# Recommendations:
# NVMe/SSD (low latency):  none or mq-deadline
# HDD (rotational):        bfq or mq-deadline
# Database server:         mq-deadline
# Desktop/mixed:           bfq (fair queuing)

# Check if device is rotational
cat /sys/block/xvda/queue/rotational    # 0 = SSD, 1 = HDD
```

## Troubleshooting Workflows

### Slow Application I/O

```bash
# 1. Confirm I/O is the bottleneck
iostat -xz 1 5    # check %util and await

# 2. Identify which process
iotop -bon 1       # or: pidstat -d 1 5

# 3. Check what files it's accessing
strace -p PID -e trace=read,write,open,close -c

# 4. Specific file I/O pattern
strace -p PID -e trace=read,write -T 2>&1 | head -100
# -T shows time spent in each syscall

# 5. Check if reads are hitting page cache or disk
# High rchar but low read_bytes in /proc/PID/io means cache hits
cat /proc/PID/io

# 6. For database workloads
# Check buffer pool hit ratio in DB metrics
# Low hit ratio = too small buffer pool = more disk I/O
```

### Filesystem Read-Only Emergency

```bash
# 1. Check dmesg for errors
dmesg | grep -i "readonly\|error\|abort\|ext4\|xfs"

# 2. Common causes:
# - EBS volume detached/error
# - Filesystem corruption detected (ext4 errors=remount-ro)
# - Disk full (some operations fail silently)

# 3. If EBS volume error
aws ec2 describe-volume-status --volume-ids vol-xxx

# 4. Remount read-write (if safe)
mount -o remount,rw /mount/point

# 5. If that fails, filesystem check needed
umount /mount/point
fsck -y /dev/xvda1         # ext4
xfs_repair /dev/xvda1      # xfs

# 6. If cannot unmount (busy)
fuser -vm /mount/point      # who's using it?
lsof +D /mount/point        # what files are open?
```
