# Process Management Reference

## Process States

Linux processes transition through several states visible in `ps` output (STAT column):

| State | Code | Description |
|-------|------|-------------|
| Running | R | Currently executing on CPU or in run queue |
| Sleeping (interruptible) | S | Waiting for event (I/O, signal, timer) — normal |
| Sleeping (uninterruptible) | D | Waiting for I/O completion — cannot be killed (disk, NFS) |
| Stopped | T | Stopped by signal (SIGSTOP/SIGTSTP) or debugger |
| Zombie | Z | Terminated but parent has not called wait() — entry remains in process table |
| Dead | X | Process fully terminated (should never be seen in `ps`) |

### Additional STAT Modifiers

- `<` — high priority (not nice to other users)
- `N` — low priority (nice to other users)
- `L` — has pages locked in memory (real-time, custom apps)
- `s` — session leader
- `l` — multi-threaded (using CLONE_THREAD)
- `+` — in the foreground process group

## ps Command Deep Dive

### Essential Invocations

```bash
# Full process list with tree structure
ps auxf

# Custom format — most useful for troubleshooting
ps -eo pid,ppid,user,stat,vsz,rss,pcpu,pmem,time,cmd --sort=-pcpu

# Thread view for a specific process
ps -T -p PID

# Process tree for a specific PID
ps -ejH | grep PID

# All processes for a specific user
ps -u username -o pid,ppid,stat,%cpu,%mem,cmd

# Processes in uninterruptible sleep (stuck I/O)
ps aux | awk '$8 ~ /D/ {print}'
```

### Key Columns Explained

| Column | Meaning | Troubleshooting Use |
|--------|---------|---------------------|
| VSZ | Virtual memory size (KB) | Includes mapped files, shared libs — not actual usage |
| RSS | Resident set size (KB) | Physical memory in use — key metric for memory pressure |
| TIME | Cumulative CPU time | High value = long-running CPU consumer |
| STAT | Process state + modifiers | D state = I/O stuck, Z = zombie, T = stopped |
| PPID | Parent process ID | Trace process ancestry, find orphans |
| NI | Nice value (-20 to 19) | Lower = higher priority |

## /proc/PID Filesystem

The `/proc/PID/` directory is the definitive source of process information:

```bash
# Process status summary (VmRSS, VmSize, State, Threads, etc.)
cat /proc/PID/status

# Memory map with sizes
cat /proc/PID/smaps_rollup

# Open file descriptors
ls -la /proc/PID/fd | wc -l    # count
ls -la /proc/PID/fd             # list targets

# File descriptor limits
cat /proc/PID/limits

# Current working directory
readlink /proc/PID/cwd

# Executable path
readlink /proc/PID/exe

# Command line arguments
cat /proc/PID/cmdline | tr '\0' ' '

# Environment variables
cat /proc/PID/environ | tr '\0' '\n'

# I/O statistics
cat /proc/PID/io
# Fields: rchar, wchar (bytes read/written including page cache)
#         read_bytes, write_bytes (actual disk I/O)
#         cancelled_write_bytes (truncated/overwritten before flush)

# Network connections
cat /proc/PID/net/tcp    # TCP connections (hex encoded)

# cgroup membership
cat /proc/PID/cgroup

# OOM score (higher = more likely to be killed)
cat /proc/PID/oom_score
cat /proc/PID/oom_score_adj    # adjustable: -1000 to 1000
```

### Key /proc/PID/status Fields

```bash
# Example output analysis:
# VmPeak:   1524800 kB   <- Peak virtual memory usage
# VmSize:   1498200 kB   <- Current virtual memory
# VmRSS:     384512 kB   <- Physical memory (what matters)
# VmSwap:      8192 kB   <- Swapped out pages (bad if high)
# Threads:       48       <- Thread count
# voluntary_ctxt_switches:  125000  <- I/O waits
# nonvoluntary_ctxt_switches: 3200  <- CPU preemption
```

High `nonvoluntary_ctxt_switches` relative to `voluntary_ctxt_switches` indicates CPU contention — the process is being preempted by the scheduler rather than voluntarily yielding.

## strace — System Call Tracing

### Common Invocations

```bash
# Attach to running process — syscall summary
strace -p PID -c
# Output: shows time spent per syscall type, count, errors

# Attach with timestamps and follow child processes
strace -p PID -f -t -e trace=network

# Trace specific syscall categories
strace -p PID -e trace=file       # open, stat, chmod, unlink, etc.
strace -p PID -e trace=network    # socket, connect, sendto, recvfrom, etc.
strace -p PID -e trace=process    # fork, exec, exit, wait
strace -p PID -e trace=memory     # mmap, mprotect, brk

# Trace a new command with output to file
strace -f -o /tmp/trace.out -T command_to_trace
# -T adds time spent in each syscall

# Show only failing syscalls
strace -p PID -Z
```

### Interpreting strace Output

```
# Example: process stuck in D state
read(5, <unfinished>    <- blocked on file descriptor 5
# Check: ls -la /proc/PID/fd/5  -> shows what file/socket is blocking

# Example: connection timeout
connect(3, {sa_family=AF_INET, sin_port=htons(3306), sin_addr=inet_addr("10.0.1.50")}, 16) = -1 ETIMEDOUT
# DB connection timing out — check network path to 10.0.1.50:3306

# Example: permission denied
open("/etc/app/config.yaml", O_RDONLY) = -1 EACCES (Permission denied)
# File permission issue — check ownership and mode
```

## ltrace — Library Call Tracing

```bash
# Trace library calls (malloc, free, strlen, etc.)
ltrace -p PID -c              # summary of library calls
ltrace -p PID -e malloc+free  # track memory allocation/deallocation
```

Useful for detecting memory leaks at the application level when `strace` shows no obvious syscall issues.

## Zombie Process Cleanup

Zombie processes (state Z) consume only a process table entry but indicate a parent that is not properly reaping children.

```bash
# Find zombies
ps aux | awk '$8 == "Z" {print $2, $11}'

# Find parent of zombie
ps -o ppid= -p ZOMBIE_PID

# Option 1: Send SIGCHLD to parent (ask it to reap)
kill -SIGCHLD PARENT_PID

# Option 2: If parent is buggy, kill parent (orphans get reparented to init/systemd)
kill PARENT_PID

# Option 3: If parent cannot be killed, zombies are harmless but ugly
# They consume only a PID and a process table slot
# Monitor: if zombie count grows unbounded, parent has a bug
```

## Nice, Renice, and Scheduling Priority

```bash
# View current nice values
ps -eo pid,ni,cmd --sort=-ni

# Start process with low priority
nice -n 19 ./heavy_batch_job.sh

# Change priority of running process
renice -n 10 -p PID            # lower priority
renice -n -5 -p PID            # higher priority (requires root)

# Real-time scheduling (use with extreme caution)
chrt -f 50 ./realtime_process   # FIFO scheduler, priority 50
chrt -r 50 ./realtime_process   # Round-robin scheduler
chrt -p PID                     # view current scheduling policy

# ionice — I/O scheduling priority
ionice -c 3 -p PID             # idle class (only I/O when nothing else needs it)
ionice -c 2 -n 7 -p PID       # best-effort, lowest priority
```

## cgroups Basics

### cgroups v2 (modern, unified hierarchy)

```bash
# Check cgroup version
mount | grep cgroup
# cgroup2 on /sys/fs/cgroup type cgroup2 -> v2

# View process cgroup membership
cat /proc/PID/cgroup

# Check resource limits for a slice
cat /sys/fs/cgroup/system.slice/service_name.service/cpu.max
# Format: "quota period" e.g., "100000 100000" = 100% of one CPU
# "200000 100000" = 200% (2 CPUs)

# Memory limit
cat /sys/fs/cgroup/system.slice/service_name.service/memory.max

# Current memory usage
cat /sys/fs/cgroup/system.slice/service_name.service/memory.current

# I/O limits
cat /sys/fs/cgroup/system.slice/service_name.service/io.max
```

### systemd Resource Controls

```bash
# View all resource settings for a service
systemctl show service_name | grep -E "(Limit|Memory|CPU|IO)"

# Key properties:
# CPUQuota=200%          -> can use 2 CPU cores
# MemoryMax=2G           -> hard memory limit (OOM kill if exceeded)
# MemoryHigh=1.5G        -> soft limit (throttle, reclaim)
# IOWeight=100           -> relative I/O priority (1-10000)
# TasksMax=512           -> max number of tasks/threads

# Set temporarily (until restart)
systemctl set-property service_name CPUQuota=150%
systemctl set-property service_name MemoryMax=2G

# Make permanent: add to service unit file under [Service]
# CPUQuota=150%
# MemoryMax=2G
# MemoryHigh=1.5G

# View resource usage for all slices
systemd-cgtop
```

## Troubleshooting Workflows

### High CPU — Single Process

```bash
# 1. Identify the process
top -bn1 | head -15

# 2. Check what it's doing at the syscall level
strace -p PID -c -f    # 10-second sample then Ctrl+C

# 3. Profile with perf (if available)
perf record -g -p PID -- sleep 10
perf report

# 4. For Java processes
jstack PID > /tmp/thread_dump_$(date +%s).txt
# Take 3 dumps 5 seconds apart, compare for stuck threads

# 5. Check if it's stuck in D state
cat /proc/PID/status | grep State
cat /proc/PID/wchan    # kernel function it's waiting in
```

### Process Cannot Start

```bash
# 1. Try starting manually to see errors
/path/to/binary --config /path/to/config 2>&1

# 2. Check library dependencies
ldd /path/to/binary | grep "not found"

# 3. Check file permissions along entire path
namei -l /path/to/binary

# 4. Check SELinux context (if enabled)
ls -Z /path/to/binary
sesearch --allow --source httpd_t --target bin_t --class file

# 5. Check ulimits
su - service_user -c "ulimit -a"

# 6. Check capabilities (if non-root needing privileged ports)
getcap /path/to/binary
# Set: setcap 'cap_net_bind_service=+ep' /path/to/binary
```

### File Descriptor Exhaustion

```bash
# 1. Check current usage vs limits
cat /proc/PID/limits | grep "open files"
ls /proc/PID/fd | wc -l

# 2. System-wide limit
cat /proc/sys/fs/file-nr
# Fields: allocated  free  maximum

# 3. See what FDs are open
ls -la /proc/PID/fd | sort -t/ -k6

# 4. Count by type
ls -la /proc/PID/fd | awk '{print $NF}' | sed 's|/.*||' | sort | uniq -c | sort -rn

# 5. Increase limits
# Per-process: /etc/security/limits.conf
#   appuser  soft  nofile  65536
#   appuser  hard  nofile  65536
# System-wide: sysctl fs.file-max=2097152
# systemd service: LimitNOFILE=65536
```
