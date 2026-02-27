# Memory Troubleshooting Reference

## /proc/meminfo Deep Dive

`/proc/meminfo` is the definitive source for system memory state. Key fields:

```bash
cat /proc/meminfo
```

### Critical Fields

| Field | Description | Troubleshooting Significance |
|-------|-------------|------------------------------|
| MemTotal | Total usable RAM | Baseline — should match instance type |
| MemFree | Completely unused RAM | Low value alone is NOT a problem |
| MemAvailable | Estimated available for new apps | THE key metric — includes reclaimable cache |
| Buffers | Block device metadata cache | Usually small (< 1 GB) |
| Cached | Page cache (file data) | Reclaimable under pressure — this is good |
| SwapTotal | Total swap space | Should be configured based on workload |
| SwapFree | Unused swap | If SwapTotal - SwapFree > 0, something was swapped |
| Dirty | Modified pages not yet written to disk | High = pending writes (check writeback) |
| Writeback | Pages being written to disk now | High = active flush (IO-bound) |
| Slab | Kernel data structure cache | Can grow large (dentry, inode caches) |
| SReclaimable | Slab cache that CAN be reclaimed | Part of "available" memory |
| SUnreclaim | Slab cache that CANNOT be reclaimed | If growing, possible kernel memory leak |
| Mapped | Memory mapped files | mmap'd files in use |
| Shmem | Shared memory (tmpfs, shm) | Includes /dev/shm, tmpfs mounts |
| KernelStack | Kernel stack memory | Grows with thread count |
| PageTables | Page table entries | Grows with number of mappings |
| AnonPages | Anonymous pages (heap, stack) | Process working memory |
| AnonHugePages | Transparent huge pages in use | If high and THP is problematic, disable |
| HugePages_Total | Explicitly allocated huge pages | Reserved, not available for other use |
| HugePages_Free | Unused huge pages | Wasted if not used by application |
| Committed_AS | Total committed memory | Can exceed physical if overcommit enabled |
| CommitLimit | Max committable memory | Based on overcommit settings |

### Memory Accounting Formula

```
Used = MemTotal - MemFree - Buffers - Cached - SReclaimable
Available = MemAvailable (kernel-computed, accounts for reclaimable + min watermarks)

# Verify: Available should be approximately:
# MemFree + (Buffers + Cached + SReclaimable) * reclaimable_fraction
```

## Page Cache vs Buffers

### Page Cache (Cached)

File data cached in memory for faster subsequent reads:

```bash
# See what's in page cache for a specific file
vmtouch /path/to/file
# Output shows: resident pages / total pages

# Evict a file from page cache
vmtouch -e /path/to/file

# Lock a file in page cache (prevent eviction)
vmtouch -l /path/to/file

# Check if a process's working set is in cache
vmtouch /path/to/data/directory/
```

Page cache is the single largest consumer of "used" memory on most systems. This is normal and beneficial. The kernel reclaims it automatically under memory pressure.

### Buffers

Block device metadata (superblocks, directory entries, inode tables):

```bash
# Usually small — if Buffers is very high:
# 1. Heavy directory traversal (find, locate, backup tools)
# 2. Filesystem metadata operations (many small files)
```

## Slab Cache (slabtop)

Kernel allocates objects from pre-sized pools called "slabs":

```bash
# View slab caches sorted by size
slabtop -o | head -20

# Key caches to watch:
# dentry          — directory entry cache (can grow huge with many files)
# inode_cache     — inode metadata cache
# ext4_inode_cache — ext4-specific inode cache
# buffer_head     — block device buffer metadata
# radix_tree_node — page cache index structures
# task_struct     — process/thread descriptors
```

### Reclaiming Slab Cache

```bash
# Check reclaimable vs unreclaimable
cat /proc/meminfo | grep -E "^S(Reclaimable|Unreclaim)"

# Force reclaim (emergency only — causes temporary I/O performance hit)
echo 2 > /proc/sys/vm/drop_caches    # free dentries and inodes
echo 3 > /proc/sys/vm/drop_caches    # free page cache + dentries + inodes

# Tune vfs_cache_pressure (default: 100)
sysctl vm.vfs_cache_pressure=50      # less aggressive slab reclaim
sysctl vm.vfs_cache_pressure=200     # more aggressive slab reclaim
```

If `SUnreclaim` is growing steadily, this may indicate a kernel memory leak. Check `dmesg` for related warnings and consider kernel update.

## Huge Pages

### Standard Huge Pages (2MB or 1GB)

Pre-allocated, reserved memory pages. Used primarily by databases (Oracle, PostgreSQL with huge_pages=on):

```bash
# Check current configuration
cat /proc/meminfo | grep -i huge
# HugePages_Total:    512      <- total allocated
# HugePages_Free:     128      <- not yet mapped
# HugePages_Rsvd:      64      <- reserved but not mapped
# HugePages_Surp:       0      <- surplus beyond pool
# Hugepagesize:      2048 kB   <- page size

# Memory consumed by huge pages: HugePages_Total * Hugepagesize
# This memory is RESERVED even if HugePages_Free > 0

# Configure huge pages
sysctl vm.nr_hugepages=512                           # persistent
echo 512 > /proc/sys/vm/nr_hugepages                 # runtime

# For 1GB pages (must be set at boot):
# Kernel parameter: hugepagesz=1G hugepages=4

# NUMA-aware allocation
echo 256 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages
echo 256 > /sys/devices/system/node/node1/hugepages/hugepages-2048kB/nr_hugepages
```

### Transparent Huge Pages (THP)

Automatically promotes 2MB pages without application changes:

```bash
# Check THP status
cat /sys/kernel/mm/transparent_hugepage/enabled
# [always] madvise never

# Check THP defrag policy
cat /sys/kernel/mm/transparent_hugepage/defrag
# [always] defer defer+madvise madvise never

# THP statistics
cat /proc/vmstat | grep thp
# thp_fault_alloc — successful THP allocations on page fault
# thp_collapse_alloc — successful THP collapses (compaction)
# thp_split_page — THP splits (fragmentation, partial access)
```

**When to disable THP:**

- Databases (MongoDB, Redis, MySQL) — THP causes latency spikes during compaction
- Real-time applications — defrag pauses are unpredictable
- Memory-sensitive workloads — THP can waste memory (2MB granularity)

```bash
# Disable THP
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag

# Persistent via grub: transparent_hugepage=never
# Or via systemd unit (RedHat/CentOS recommended approach)
```

## NUMA (Non-Uniform Memory Access)

On multi-socket or large instance types, memory access latency depends on which CPU socket "owns" the memory:

```bash
# Check NUMA topology
numactl --hardware
# node 0: cpus: 0-15, memory: 32768 MB
# node 1: cpus: 16-31, memory: 32768 MB

# NUMA statistics
numastat
# numa_hit    — allocations on intended node (good)
# numa_miss   — allocations on remote node (bad — latency penalty)
# numa_foreign — another node allocated here (cross-node)

# Per-process NUMA stats
numastat -p PID

# Pin process to NUMA node
numactl --cpunodebind=0 --membind=0 /path/to/application

# Check if process memory is balanced across nodes
numastat -c PID
```

**NUMA imbalance symptoms:**

- Inconsistent latency despite low overall CPU/memory usage
- One NUMA node shows high `numa_miss` count
- `perf stat -e cache-misses` shows high remote DRAM access

## OOM Killer

The Out-Of-Memory killer activates when the system cannot reclaim enough memory.

### How OOM Scoring Works

```bash
# View OOM score for a process (0-1000, higher = more likely to be killed)
cat /proc/PID/oom_score

# OOM score adjustment (-1000 to 1000)
cat /proc/PID/oom_score_adj
# -1000 = never kill (OOM disabled for this process)
#     0 = normal (default)
#  1000 = always kill first

# Set OOM adjustment
echo -500 > /proc/PID/oom_score_adj    # less likely to be killed
echo -1000 > /proc/PID/oom_score_adj   # immune to OOM killer

# For systemd services:
# [Service]
# OOMScoreAdjust=-500
```

### OOM Killer Scoring Algorithm

```
oom_score = (process_RSS / total_RAM) * 1000 + oom_score_adj

Factors that increase score:
- Higher RSS (physical memory usage)
- Higher oom_score_adj
- Process is not root (root gets slight bonus)
- Process has forked recently (child processes scored similarly)

Factors that decrease score:
- Lower RSS
- Negative oom_score_adj
- Process is root (small reduction)
- CAP_SYS_ADMIN capability
```

### Investigating OOM Events

```bash
# Check for OOM kills
dmesg | grep -i "out of memory"
journalctl -k | grep -i "oom\|killed process"

# Detailed OOM dump shows:
# - All process memory usage at time of kill
# - Which process was selected and why
# - Memory zone information (normal, DMA, etc.)

# Parse OOM logs for killed process info
dmesg | grep -A 5 "Killed process"
# Killed process 12345 (java) total-vm:8388608kB, anon-rss:4194304kB, file-rss:2048kB

# Check OOM invocation count
cat /proc/vmstat | grep oom_kill
```

### Preventing OOM Kills

```bash
# 1. Overcommit tuning
sysctl vm.overcommit_memory
# 0 = heuristic (default — kernel guesses)
# 1 = always overcommit (dangerous)
# 2 = strict — never overcommit beyond swap + ratio% of RAM

sysctl vm.overcommit_ratio        # used with overcommit_memory=2
# CommitLimit = swap + (RAM * ratio / 100)

# 2. Set appropriate OOM scores
echo -500 > /proc/$(pidof critical_db)/oom_score_adj

# 3. Use cgroup memory limits (preferred)
# Memory.max in cgroup = process gets OOM'd within its cgroup before system OOM

# 4. Monitor memory trends
# Set up alerts for MemAvailable < 10% of MemTotal
```

## Swappiness Tuning

Controls the kernel's tendency to swap anonymous pages vs reclaiming page cache:

```bash
# Check current value
sysctl vm.swappiness     # default: 60

# Values:
# 0   = swap only to avoid OOM (nearly disable swap)
# 1   = minimum swapping (recommended for databases)
# 10  = reduce swapping (good for most servers)
# 60  = default balance
# 100 = aggressively swap to keep cache full

# Set temporarily
sysctl -w vm.swappiness=10

# Set permanently
echo "vm.swappiness=10" >> /etc/sysctl.d/99-tuning.conf
sysctl -p /etc/sysctl.d/99-tuning.conf
```

**Recommended settings:**

| Workload | swappiness | Rationale |
|----------|-----------|-----------|
| Database server | 1-10 | Keep working set in RAM, avoid swap latency |
| Web application | 10-30 | Some swapping OK for inactive pages |
| General purpose | 60 | Default, balanced |
| Batch processing | 60-80 | Favor caching large files over keeping inactive apps |

## Memory cgroups

### cgroups v2 Memory Controller

```bash
# Check memory limit
cat /sys/fs/cgroup/system.slice/myservice.service/memory.max
# "max" means unlimited

# Current usage
cat /sys/fs/cgroup/system.slice/myservice.service/memory.current

# Usage breakdown
cat /sys/fs/cgroup/system.slice/myservice.service/memory.stat
# Key fields:
# anon      — anonymous pages (heap, stack)
# file      — page cache pages
# slab      — kernel slab objects
# sock      — network buffers
# pgfault   — page faults
# pgmajfault — major page faults (required disk I/O)

# Memory events (OOM kills, reclaim events)
cat /sys/fs/cgroup/system.slice/myservice.service/memory.events
# low      — approached memory.low (soft protection boundary)
# high     — hit memory.high (throttled)
# max      — hit memory.max (reclaim attempted)
# oom      — OOM within cgroup
# oom_kill — process killed within cgroup

# Set limits via systemd
systemctl set-property myservice.service MemoryMax=4G
systemctl set-property myservice.service MemoryHigh=3G
```

### Memory Limit Hierarchy

```
memory.min    — hard minimum guarantee (never reclaimed)
memory.low    — soft minimum (reclaimed only under global pressure)
memory.high   — soft maximum (process throttled, pages reclaimed)
memory.max    — hard maximum (OOM kill within cgroup if exceeded)

Recommendation:
  memory.high = expected working set * 1.2 (with throttling as warning)
  memory.max  = absolute limit (OOM if exceeded)
```

## Troubleshooting Workflows

### Memory Leak Detection

```bash
# 1. Baseline RSS for suspect process
ps -o pid,rss,vsz,cmd -p PID

# 2. Track RSS over time
while true; do
  echo "$(date +%H:%M:%S) $(cat /proc/PID/status | grep VmRSS)"
  sleep 60
done > /tmp/rss_tracking.log

# 3. Check if it's heap growth
cat /proc/PID/smaps | grep -A 3 "[heap]"
# Rss growing = heap leak

# 4. For native code
valgrind --tool=massif --pages-as-heap=yes ./application
# Or: gdb attach + heap analysis

# 5. For Java
jmap -histo:live PID | head -30      # object histogram
jmap -dump:format=b,file=/tmp/heap.hprof PID    # heap dump

# 6. For Python
# Enable tracemalloc in application code
# Or: py-spy dump --pid PID
```

### Sudden Memory Spike

```bash
# 1. Check for fork bomb or runaway process spawning
ps aux --sort=-rss | head -20
ps -eo pid,ppid,rss,cmd | awk '{total[$4]+=$3} END {for (cmd in total) print total[cmd], cmd}' | sort -rn | head

# 2. Check for memory-mapped files growing
cat /proc/PID/maps | wc -l     # number of mappings
cat /proc/PID/smaps_rollup      # aggregate mapping sizes

# 3. Check tmpfs usage (counts as memory)
df -h | grep tmpfs
# /dev/shm and /tmp (if tmpfs) consume RAM

# 4. Check for slab growth
slabtop -o | head -10

# 5. Check kernel memory
cat /proc/meminfo | grep -E "^(KernelStack|PageTables|VmallocUsed)"
```

### Swap Storm Recovery

```bash
# 1. Assess the situation
free -h                           # how much swap in use?
vmstat 1 5                        # si/so columns — active swapping rate?

# 2. Identify what's in swap
for pid in /proc/[0-9]*; do
  name=$(cat $pid/comm 2>/dev/null)
  swap=$(grep VmSwap $pid/status 2>/dev/null | awk '{print $2}')
  [ -n "$swap" ] && [ "$swap" -gt 0 ] && echo "$swap kB $name ($(basename $pid))"
done | sort -rn | head -20

# 3. If specific process is swapped, consider:
# - Increase its oom_score_adj (make it less likely to be kept in swap)
# - Restart it (will load fresh from disk, not from swap)
# - Increase RAM on the instance

# 4. Emergency: disable swap (DANGEROUS if memory is truly low)
# swapoff -a    # forces all swapped pages back to RAM — can cause OOM

# 5. Better: reduce memory pressure first, then swap will drain naturally
# Kill or restart non-critical high-RSS processes
```
