---
name: linux-admin
description: "Linux system administration troubleshooting — covers process management, disk I/O analysis, memory troubleshooting, network diagnostics, log analysis, and performance tuning. Includes decision trees for CPU high, memory pressure, disk issues, network problems, and service failures."
metadata:
  author: agenticops
  version: "1.0"
  domain: infrastructure
---

# Linux Admin Skill

## Quick Decision Trees

### CPU High

1. `top -bn1 | head -20` — identify top processes
2. `ps aux --sort=-%cpu | head -10` — CPU consumers
3. If system CPU high: `vmstat 1 5` — check for I/O wait
4. If I/O wait high -> go to Disk I/O section
5. If user CPU high -> check process with `strace -p PID -c` for syscall breakdown
6. Check for runaway processes: `ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%cpu | head`

**Escalation path:**

```
CPU > 90% for 5+ minutes
  |
  +-- User CPU high?
  |     +-- Single process? -> strace/perf, check for infinite loops
  |     +-- Many processes? -> check load average vs CPU count, possible fork bomb
  |
  +-- System CPU high?
  |     +-- High I/O wait? -> Disk I/O tree
  |     +-- High softirq? -> Network interrupt coalescing, check `cat /proc/interrupts`
  |     +-- High steal? -> Noisy neighbor (shared host) or CPU credits exhausted (T-series)
  |
  +-- CPU throttling?
        +-- Check `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
        +-- cgroup limits: `cat /sys/fs/cgroup/cpu/docker/*/cpu.stat`
```

**Key metrics to collect:**

- `mpstat -P ALL 1 5` — per-CPU breakdown (usr, sys, iowait, steal, idle)
- `pidstat 1 5` — per-process CPU usage over time
- `/proc/loadavg` — 1/5/15 min load averages + running/total processes
- `perf top` — real-time function-level CPU profiling (requires perf tools)

### Memory Pressure

1. `free -h` — check available/used/cache
2. `vmstat 1 5` — check si/so (swap in/out)
3. If swap active: `swapon --show` then check OOM killer: `dmesg | grep -i "out of memory"`
4. Top memory consumers: `ps aux --sort=-%mem | head -10`
5. Memory by process: `smem -t -k -c "pid user command swap pss"`
6. Check for memory leaks: `cat /proc/PID/status | grep Vm`

**Escalation path:**

```
Available memory < 10% AND swap active
  |
  +-- Sudden drop?
  |     +-- Check `dmesg -T | tail -100` for OOM events
  |     +-- Recent deployment? -> Rollback candidate
  |
  +-- Gradual increase?
  |     +-- Memory leak likely -> Track RSS over time with `pidstat -r 60`
  |     +-- Check `/proc/PID/smaps_rollup` for PSS growth
  |
  +-- Cache pressure?
        +-- `cat /proc/meminfo | grep -E "^(Cached|Buffers|SReclaimable)"`
        +-- If SReclaimable high: `slabtop -o | head -20` — check dentry/inode cache
        +-- Drop caches (emergency): `echo 3 > /proc/sys/vm/drop_caches`
```

**Key metrics to collect:**

- `free -h` — human-readable memory overview
- `cat /proc/meminfo` — detailed kernel memory counters
- `vmstat 1 10` — si/so columns show swap activity rate
- `ps aux --sort=-%mem | head -20` — top RSS consumers

### Disk Issues

1. `df -h` — check filesystem usage
2. `du -sh /* 2>/dev/null | sort -rh | head -10` — largest directories
3. If disk I/O slow: `iostat -xz 1 5` — check %util, await, avgqu-sz
4. `iotop -bon 1` — identify I/O-heavy processes
5. Check for filesystem errors: `dmesg | grep -i "error\|fault\|readonly"`
6. Inode exhaustion: `df -i`

**Escalation path:**

```
Disk usage > 90% OR I/O latency > 50ms
  |
  +-- Space exhaustion?
  |     +-- Find large files: `find / -xdev -type f -size +100M -exec ls -lh {} \; 2>/dev/null`
  |     +-- Deleted but open files: `lsof +L1`
  |     +-- Log rotation stuck: `ls -la /var/log/*.gz | wc -l`
  |
  +-- I/O latency?
  |     +-- %util near 100%? -> Device saturated
  |     +-- avgqu-sz high? -> Too many concurrent requests
  |     +-- await >> svctm? -> Queuing delay, consider IOPS upgrade
  |     +-- EBS: check CloudWatch VolumeQueueLength, BurstBalance
  |
  +-- Filesystem errors?
        +-- `dmesg | grep -i "ext4\|xfs\|readonly"`
        +-- If read-only: filesystem corruption or EBS detach event
        +-- `xfs_repair -n /dev/sdX` (dry run) or `fsck -n /dev/sdX`
```

**Key metrics to collect:**

- `iostat -xz 1 5` — per-device I/O stats
- `iotop -bon 1` — per-process I/O activity
- `df -h && df -i` — space and inode usage
- `lsblk` — block device topology

### Network Problems

1. `ss -tuln` — listening ports
2. `ss -s` — socket statistics summary
3. `netstat -i` or `ip -s link` — interface errors/drops
4. DNS resolution: `dig +short example.com` and `cat /etc/resolv.conf`
5. Connectivity: `ping -c 3 gateway_ip` then `traceroute target`
6. Connection tracking: `conntrack -S` (if available) or `cat /proc/net/nf_conntrack | wc -l`
7. Bandwidth: `iftop -i eth0` or `nload`

**Escalation path:**

```
Network unreachable OR high latency/packet loss
  |
  +-- Interface down?
  |     +-- `ip link show` — check state UP/DOWN
  |     +-- `ethtool eth0` — check link detected, speed, duplex
  |
  +-- Packet loss?
  |     +-- `ip -s link show eth0` — RX/TX errors, drops, overruns
  |     +-- Ring buffer: `ethtool -g eth0` — check current vs max
  |     +-- `ethtool -S eth0 | grep -i "drop\|error\|miss"`
  |
  +-- DNS failure?
  |     +-- `dig +trace target` — find where resolution breaks
  |     +-- `systemd-resolve --status` — check DNS config
  |
  +-- Connection refused?
        +-- `ss -tuln | grep :PORT` — is service listening?
        +-- `iptables -L -n -v | grep PORT` — firewall blocking?
        +-- SELinux: `sestatus` and `ausearch -m AVC -ts recent`
```

### Service Failures

1. `systemctl status service_name` — check loaded/active/main PID
2. `journalctl -u service_name --no-pager -n 50` — recent logs
3. `systemctl list-dependencies service_name` — dependency chain
4. Check for port conflicts: `ss -tuln | grep :PORT`
5. Check permissions: `ls -la /path/to/config` and `namei -l /path/to/binary`
6. Resource limits: `systemctl show service_name | grep Limit`

**Escalation path:**

```
Service not running or crash-looping
  |
  +-- Failed to start?
  |     +-- Check exit code: `systemctl show -p ExecMainStatus service_name`
  |     +-- Dependency failed: `systemctl list-dependencies --reverse service_name`
  |     +-- Config syntax: most services have `--test` or `--check` flag
  |
  +-- Crash-looping?
  |     +-- `journalctl -u service_name --since "10 min ago" --no-pager`
  |     +-- OOM killed? `dmesg | grep -i "killed process"`
  |     +-- Segfault? `coredumpctl list` then `coredumpctl info`
  |
  +-- Running but unresponsive?
        +-- `strace -p PID -c -f -t` — check what syscalls it's stuck on
        +-- Thread dump (Java): `kill -3 PID` or `jstack PID`
        +-- File descriptors: `ls /proc/PID/fd | wc -l` vs `cat /proc/PID/limits`
```

**Key checks:**

- `systemctl is-failed service_name` — quick check
- `systemctl cat service_name` — view full unit file
- `systemctl show service_name -p Restart,RestartSec,StartLimitBurst` — restart policy
- `loginctl show-user $(whoami)` — check if lingering enabled for user services

## Common Patterns

### Log Analysis

- System logs: `journalctl -p err --since "1 hour ago" --no-pager`
- Auth failures: `journalctl -u sshd --no-pager -n 100 | grep -i "failed\|invalid"`
- Kernel messages: `dmesg -T | tail -50`
- Application logs: `tail -f /var/log/application.log | grep -i error`
- Structured log parsing: `journalctl -o json -u service_name | jq '.MESSAGE'`
- Multi-service correlation: `journalctl --since "2024-01-01 12:00" --until "2024-01-01 12:05" --no-pager`

**Log analysis workflow:**

```
1. Start broad:    journalctl -p err --since "1 hour ago" | head -50
2. Narrow by unit: journalctl -u suspect_service --since "1 hour ago"
3. Add context:    journalctl -u suspect_service -B 5 -A 5 | grep -i error
4. Correlate:      journalctl --since "TIMESTAMP" --until "+5s" (all units)
5. Check kernel:   dmesg -T | grep -i "error\|warn\|kill\|oom"
```

### Performance Baseline

- CPU: `mpstat -P ALL 1 5`
- Memory: `free -h && vmstat 1 5`
- Disk: `iostat -xz 1 5`
- Network: `sar -n DEV 1 5`
- Load: `uptime && cat /proc/loadavg`
- All-in-one snapshot: `sar -A 1 1`

**Baseline collection script:**

```bash
#!/bin/bash
# Collect 60-second performance baseline
OUTDIR="/tmp/baseline-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTDIR"
mpstat -P ALL 1 60 > "$OUTDIR/cpu.txt" &
vmstat 1 60 > "$OUTDIR/vmstat.txt" &
iostat -xz 1 60 > "$OUTDIR/iostat.txt" &
sar -n DEV 1 60 > "$OUTDIR/network.txt" &
pidstat -urd 1 60 > "$OUTDIR/pidstat.txt" &
wait
echo "Baseline collected in $OUTDIR"
```

### Security Quick Check

- Open ports: `ss -tuln`
- Active connections: `ss -tun`
- Running processes: `ps auxf`
- Recent logins: `last -10`
- Failed logins: `lastb -10 2>/dev/null || journalctl -u sshd | grep Failed`
- Suspicious cron: `for user in $(cut -f1 -d: /etc/passwd); do crontab -l -u $user 2>/dev/null; done`
- SUID binaries: `find / -perm -4000 -type f 2>/dev/null`
- World-writable files: `find /etc -perm -o+w -type f 2>/dev/null`

### Emergency Response Playbook

```
System unresponsive but SSH works:
  1. `uptime` — load average sanity check
  2. `free -h` — memory status
  3. `dmesg -T | tail -20` — kernel messages
  4. `ps aux --sort=-%cpu | head -5` — CPU hog
  5. `ps aux --sort=-%mem | head -5` — memory hog
  6. `iostat -xz 1 1` — disk saturation
  7. If OOM imminent: identify and kill lowest-priority process
  8. If disk full: `lsof +L1` for deleted-but-open, clear old logs
```

## Tool Reference Quick Card

| Tool | Purpose | Key Flags |
|------|---------|-----------|
| `top` / `htop` | Real-time process monitor | `top -bn1`, htop has tree view |
| `ps` | Process snapshot | `aux`, `-eo pid,ppid,cmd,%cpu,%mem`, `auxf` (tree) |
| `vmstat` | Virtual memory stats | `vmstat 1 5` (1s interval, 5 samples) |
| `mpstat` | Per-CPU stats | `-P ALL 1 5` |
| `iostat` | Disk I/O stats | `-xz 1 5` (extended, skip idle) |
| `iotop` | Per-process I/O | `-bon 1` (batch, non-interactive) |
| `pidstat` | Per-process stats | `-urd 1 5` (CPU, mem, I/O) |
| `free` | Memory overview | `-h` (human-readable) |
| `df` | Filesystem space | `-h`, `-i` (inodes) |
| `du` | Directory space | `-sh /path`, `--max-depth=1` |
| `ss` | Socket stats | `-tuln` (TCP/UDP listen), `-s` (summary) |
| `ip` | Network config | `addr show`, `route show`, `-s link` |
| `strace` | Syscall trace | `-p PID -c` (summary), `-f` (follow forks) |
| `perf` | CPU profiling | `perf top`, `perf record -g -p PID` |
| `dmesg` | Kernel ring buffer | `-T` (human timestamps), `-l err` |
| `journalctl` | Systemd journal | `-u unit`, `-p err`, `--since`, `-f` (follow) |
| `lsof` | Open files | `+L1` (deleted), `-i :PORT`, `-p PID` |
| `slabtop` | Kernel slab cache | `-o` (batch mode) |
| `smem` | Memory reporting | `-t -k -c "pid user command swap pss"` |
| `ethtool` | NIC diagnostics | `-g` (ring buffer), `-S` (stats), `-i` (driver) |
