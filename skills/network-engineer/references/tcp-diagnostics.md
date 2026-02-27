# TCP Diagnostics Reference

## TCP Connection States

### State Machine

```
Client                              Server
  |                                   |
  |--- SYN --------------------------->|  Client: SYN_SENT
  |                                   |  Server: SYN_RECV
  |<--- SYN+ACK ----------------------|
  |                                   |
  |--- ACK --------------------------->|  Both: ESTABLISHED
  |                                   |
  |  ... data transfer ...            |
  |                                   |
  |--- FIN --------------------------->|  Client: FIN_WAIT_1
  |                                   |  Server: CLOSE_WAIT
  |<--- ACK --------------------------|  Client: FIN_WAIT_2
  |                                   |
  |<--- FIN --------------------------|  Server: LAST_ACK
  |--- ACK --------------------------->|  Client: TIME_WAIT
  |                                   |  Server: CLOSED
  |  (wait 2*MSL)                     |
  |  Client: CLOSED                   |
```

### State Reference

| State | Who | Description | Duration | Troubleshooting |
|-------|-----|-------------|----------|-----------------|
| LISTEN | Server | Waiting for connections | Indefinite | Normal — service is accepting connections |
| SYN_SENT | Client | SYN sent, waiting for SYN-ACK | ~75s (retries) | Firewall blocking, server down, or network issue |
| SYN_RECV | Server | SYN received, SYN-ACK sent | ~75s (retries) | SYN flood attack, or client-side firewall |
| ESTABLISHED | Both | Connection active | Indefinite | Normal — data can flow |
| FIN_WAIT_1 | Closer | FIN sent, waiting for ACK | Seconds | If stuck: remote side not responding |
| FIN_WAIT_2 | Closer | FIN ACK'd, waiting for remote FIN | tcp_fin_timeout (60s) | Remote app hasn't closed its side |
| TIME_WAIT | Closer | Both FINs exchanged, waiting | 2*MSL (60s default) | Normal — prevents late packet confusion |
| CLOSE_WAIT | Other | Received FIN, waiting for app to close | Indefinite | Application bug — not calling close() |
| LAST_ACK | Other | FIN sent, waiting for final ACK | Seconds | Network issue or peer not ACK'ing |
| CLOSING | Both | Both sides sent FIN simultaneously | Seconds | Rare — simultaneous close |

### Monitoring Connection States

```bash
# Count connections by state
ss -tn | awk '{print $1}' | sort | uniq -c | sort -rn

# Or with ss state filter
ss -tn state established | wc -l
ss -tn state time-wait | wc -l
ss -tn state close-wait | wc -l
ss -tn state syn-recv | wc -l

# Connections per remote host (top talkers)
ss -tn state established | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head

# Watch states in real-time
watch -n 1 'ss -s'
```

### Problematic States

**CLOSE_WAIT accumulation:**

```bash
# Find processes with CLOSE_WAIT connections
ss -tnp state close-wait

# CLOSE_WAIT means:
# 1. Remote side sent FIN (wants to close)
# 2. Local side ACK'd the FIN
# 3. Local application has NOT called close() on the socket
# -> This is ALWAYS a local application bug

# Common causes:
# - Connection pool not releasing connections
# - Missing finally/defer block for socket cleanup
# - Application stuck in processing, never reaches close()

# Fix: application code must close the socket
# Workaround: restart the application
```

**TIME_WAIT accumulation:**

```bash
# Count TIME_WAIT connections
ss -tn state time-wait | wc -l

# TIME_WAIT is NORMAL — prevents late packet from previous connection
# confusing a new connection on the same port pair

# Problematic when:
# - Thousands of short-lived connections (API servers, proxies)
# - Running out of ephemeral ports

# Mitigation:
sysctl -w net.ipv4.tcp_tw_reuse=1        # reuse TIME_WAIT for outbound connections
sysctl -w net.ipv4.ip_local_port_range="1024 65535"   # more ephemeral ports

# Check ephemeral port usage
ss -tn | awk '{print $4}' | cut -d: -f2 | sort -n | tail
sysctl net.ipv4.ip_local_port_range      # available range
```

**SYN_RECV flood:**

```bash
# High SYN_RECV count may indicate SYN flood attack
ss -tn state syn-recv | wc -l

# Check source IPs
ss -tn state syn-recv | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head

# Enable SYN cookies (usually already enabled)
sysctl -w net.ipv4.tcp_syncookies=1

# Increase SYN backlog
sysctl -w net.ipv4.tcp_max_syn_backlog=8192

# Increase somaxconn (listen backlog limit)
sysctl -w net.core.somaxconn=4096
```

## TCP Window Sizing

### How TCP Window Works

```
TCP uses a sliding window for flow control:

Sender window = min(receiver_window, congestion_window)

receiver_window (rwnd):
  - Advertised by receiver in ACK packets
  - Limits how much data sender can send before getting ACK
  - Based on receiver's available buffer space

congestion_window (cwnd):
  - Maintained by sender
  - Limits sending rate based on network capacity
  - Starts small (slow start) and grows
  - Shrinks on packet loss detection

Effective throughput = window_size / RTT
  Example: 64KB window, 100ms RTT = 640 KB/s = 5.12 Mbps
  For 1 Gbps link with 100ms RTT: need ~12.5 MB window
```

### Window Scaling

```bash
# TCP window scale option (RFC 7323)
# Allows window sizes > 64KB (original 16-bit window field limit)
# Scale factor: 0-14, applied as: window_size = advertised_window << scale_factor

# Check if window scaling is enabled
sysctl net.ipv4.tcp_window_scaling    # should be 1

# View window scale for active connections
ss -ti | grep wscale
# Example: wscale:7,7  -> scale factor 7 on both sides -> max window = 64KB << 7 = 8MB

# Auto-tuning (kernel adjusts window based on available memory)
sysctl net.ipv4.tcp_rmem    # min default max (receive buffer)
sysctl net.ipv4.tcp_wmem    # min default max (send buffer)

# For high-bandwidth long-distance links:
sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"    # max 16MB receive buffer
sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"    # max 16MB send buffer
sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.wmem_max=16777216
```

### Bandwidth-Delay Product

```
BDP = bandwidth * RTT

Example:
  1 Gbps link, 50ms RTT
  BDP = 125 MB/s * 0.05s = 6.25 MB

  TCP window must be >= BDP for full link utilization
  If window < BDP, link is underutilized

Diagnosis:
  # Check connection details
  ss -ti dst target_ip
  # Look for: rcv_space, cwnd, send, rtt

  # If cwnd * MSS < BDP -> congestion window too small
  # If rcv_space < BDP -> receive window too small
```

## Slow Start and Congestion Control

### TCP Slow Start

```
Initial cwnd = typically 10 MSS (segments) on modern Linux
  = 10 * 1460 bytes = 14.6 KB

Slow start phase:
  - cwnd doubles every RTT (exponential growth)
  - Until: packet loss detected OR cwnd reaches ssthresh

  RTT 0: cwnd = 10 MSS  -> 14.6 KB
  RTT 1: cwnd = 20 MSS  -> 29.2 KB
  RTT 2: cwnd = 40 MSS  -> 58.4 KB
  RTT 3: cwnd = 80 MSS  -> 116.8 KB
  ...

Time to reach full speed = RTT * log2(BDP / initial_cwnd)
  Example: 50ms RTT, 6.25 MB BDP, 14.6 KB initial
  log2(6250/14.6) = ~8.7 RTTs = ~435ms to reach full speed!

Impact: Short connections (HTTP requests) may never leave slow start
```

### Congestion Control Algorithms

```bash
# Check current algorithm
sysctl net.ipv4.tcp_congestion_control
# Common: cubic (default), bbr, reno

# Available algorithms
sysctl net.ipv4.tcp_available_congestion_control

# Change algorithm
sysctl -w net.ipv4.tcp_congestion_control=bbr
# BBR requires: modprobe tcp_bbr

# Algorithm comparison:
# cubic: loss-based, default on most Linux
#   - Grows cwnd aggressively, backs off on loss
#   - Good for most scenarios
#
# bbr: model-based (Google)
#   - Estimates bottleneck bandwidth and RTT
#   - Better on lossy links (wireless, long-distance)
#   - Less affected by random packet loss
#   - Requires Linux 4.9+
#
# reno: simple loss-based (legacy)
#   - Linear cwnd growth in congestion avoidance
#   - Poor recovery from multiple losses
```

### Diagnosing Congestion

```bash
# Check per-connection congestion info
ss -ti dst target_ip
# Key fields:
# cwnd:N       — current congestion window (in MSS units)
# ssthresh:N   — slow start threshold
# rtt:N/M      — smoothed RTT / RTT variance (ms)
# retrans:X/Y  — current/total retransmissions
# bytes_sent:N — total bytes sent
# send Xbps    — current send rate

# If cwnd is small and not growing:
# -> Packet loss keeping cwnd small
# -> Check for retransmissions

# If rtt is high and variable:
# -> Network congestion or bufferbloat
# -> Check intermediate hops with mtr

# Monitor retransmissions
cat /proc/net/snmp | grep Tcp
# TCPRetransSegs / TCPOutSegs = retransmit ratio
# > 1% is concerning, > 5% is severe
```

## MSS/MTU Relationship

```
MTU (Maximum Transmission Unit):
  - Maximum frame size at Layer 2
  - Ethernet default: 1500 bytes
  - Jumbo frames: 9001 bytes (within AWS VPC)

MSS (Maximum Segment Size):
  - Maximum TCP payload per segment
  - Negotiated during TCP handshake (SYN)
  - MSS = MTU - IP header (20) - TCP header (20) = 1460 bytes typically

  Standard:  MTU 1500  -> MSS 1460
  Jumbo:     MTU 9001  -> MSS 8961
  VPN/GRE:   MTU 1500  -> effective MTU ~1420-1440 -> MSS ~1380-1400
  PPPoE:     MTU 1492  -> MSS 1452
```

### MTU Troubleshooting

```bash
# Check interface MTU
ip link show | grep mtu

# Test path MTU with don't-fragment bit
ping -M do -s 1472 -c 1 target    # 1472 + 28 = 1500
# If fails: "message too long" or "frag needed"

# Binary search for path MTU
for size in 1472 1400 1300 1200 1100 1000; do
  ping -M do -s $size -c 1 -W 2 target 2>/dev/null && echo "MTU >= $((size + 28))" && break
done

# Check PMTUD (Path MTU Discovery) cached value
ip route get target_ip
# If "mtu X" shown, PMTUD has detected a lower MTU

# Common MTU issues:
# 1. VPN tunnel reduces effective MTU by 20-60 bytes
# 2. Docker/container overlay networks add headers
# 3. Jumbo frames work within VPC but not over Internet/VPN
# 4. PMTUD blocked by firewalls dropping ICMP "frag needed"

# Fix for PMTUD failure (clamp MSS on firewall)
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
  -j TCPMSS --clamp-mss-to-pmtu
```

## TCP Keepalive

```bash
# System defaults
sysctl net.ipv4.tcp_keepalive_time      # 7200s (2 hours!) before first probe
sysctl net.ipv4.tcp_keepalive_intvl     # 75s between probes
sysctl net.ipv4.tcp_keepalive_probes    # 9 probes before declaring dead

# Total detection time (defaults): 7200 + 75*9 = 7875 seconds = ~2 hours 11 minutes
# This is usually too slow for production services

# Recommended for servers behind load balancers:
sysctl -w net.ipv4.tcp_keepalive_time=60
sysctl -w net.ipv4.tcp_keepalive_intvl=10
sysctl -w net.ipv4.tcp_keepalive_probes=6
# Detection time: 60 + 10*6 = 120 seconds

# Per-socket keepalive (application sets via setsockopt)
# SO_KEEPALIVE = 1 (enable)
# TCP_KEEPIDLE = seconds before first probe
# TCP_KEEPINTVL = seconds between probes
# TCP_KEEPCNT = number of probes

# Check if keepalive is enabled on a connection
ss -to state established
# Look for "timer:(keepalive, ...)"

# AWS ELB/NLB idle timeout:
# ALB: 60 seconds default (configurable 1-4000)
# NLB: 350 seconds for TCP
# Must set application keepalive < LB idle timeout
```

## Connection Timeouts

### TCP Connection Establishment Timeout

```bash
# SYN retransmit behavior
sysctl net.ipv4.tcp_syn_retries     # default: 6
# Retransmit intervals: 1, 2, 4, 8, 16, 32 seconds
# Total timeout: ~127 seconds

sysctl net.ipv4.tcp_synack_retries  # default: 5
# For SYN-ACK retransmits on server side

# Reduce for faster failure detection
sysctl -w net.ipv4.tcp_syn_retries=3     # ~15 seconds total
sysctl -w net.ipv4.tcp_synack_retries=3
```

### Application-Level Timeouts

```bash
# Test connection timeout
timeout 5 bash -c 'echo > /dev/tcp/target_ip/port' 2>/dev/null && echo "OPEN" || echo "CLOSED/TIMEOUT"

# curl with connect timeout
curl --connect-timeout 5 --max-time 30 http://target

# Test with specific timeout using nc
nc -zv -w 5 target_ip port    # 5 second timeout
```

## TCP Retransmission Behavior

### Retransmission Detection

```bash
# System-wide retransmit statistics
cat /proc/net/snmp | grep Tcp
# Key fields:
# RetransSegs: total retransmitted segments (cumulative counter)
# OutSegs: total segments sent
# Ratio = RetransSegs / OutSegs

# Per-connection retransmits
ss -ti dst target_ip
# retrans:X/Y -> X=current unacked retransmits, Y=total retransmits

# Watch retransmit rate over time
watch -n 1 'cat /proc/net/snmp | grep Tcp | awk "{print \"RetransSegs:\", \$13, \"OutSegs:\", \$12}"'

# Detailed retransmit events (netstat)
netstat -s | grep -i retransmit
# TCPLossProbes: loss probes sent (TLP — tail loss probe)
# TCPLostRetransmit: retransmits lost (double loss!)
# TCPFastRetrans: fast retransmits (3 dup ACKs)
# TCPSlowStartRetrans: retransmits during slow start
# TCPSynRetrans: SYN retransmits
```

### Retransmission Mechanisms

```
1. RTO (Retransmission Timeout):
   - Timer-based, fires when ACK not received within timeout
   - RTO = SRTT + 4*RTTVAR (smoothed RTT + variance)
   - Minimum RTO: 200ms (Linux default)
   - After timeout: cwnd = 1 MSS (back to slow start)
   - Exponential backoff: RTO doubles on each retry

2. Fast Retransmit:
   - Triggered by 3 duplicate ACKs (same ACK number received 4 times total)
   - Assumes segment loss (not reordering)
   - cwnd reduced to half (not back to 1)
   - Faster recovery than RTO

3. Tail Loss Probe (TLP):
   - Probes for loss at the tail of a burst
   - Sends retransmit of last unACK'd segment after 2*SRTT
   - Avoids waiting for full RTO
   - Enabled by default: sysctl net.ipv4.tcp_early_retrans

4. RACK (Recent Acknowledgment):
   - Time-based loss detection (replaces dup-ACK counting)
   - Uses timestamp to determine if segment is lost
   - Better than dup-ACK for reordered packets
   - Default on modern Linux
```

## Troubleshooting Workflows

### Slow TCP Transfers

```bash
# 1. Check connection parameters
ss -ti dst target_ip
# Look at: cwnd, ssthresh, rtt, retrans, send rate

# 2. Is it congestion limited?
# cwnd small + retransmissions -> yes
# Fix: check for packet loss in path (mtr)

# 3. Is it window limited?
# rcv_space small -> receiver window too small
# Fix: increase tcp_rmem on receiver

# 4. Is it application limited?
# send rate << cwnd * MSS / RTT -> application not sending fast enough
# Fix: application issue (slow disk, CPU, etc.)

# 5. Measure actual throughput
iperf3 -c target_ip -t 10 -P 4    # 10s test, 4 parallel streams
# Compare with expected bandwidth

# 6. Check for bandwidth throttling
# AWS instance type limits (e.g., m5.xlarge = 10 Gbps burst)
# EBS throughput limits may also be a bottleneck
```

### TCP RST (Reset) Analysis

```bash
# Capture RST packets
tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-rst != 0' -c 20

# Common RST causes:
# 1. Connection to closed port -> immediate RST
# 2. Firewall sending RST (reject vs drop)
# 3. Application crash/abort
# 4. Half-open connection detection (one side crashed)
# 5. Load balancer timeout (idle connection removed)
# 6. TCP keepalive failure (peer unreachable)

# Differentiate RST sources:
# RST from target port -> port not listening or app rejected
# RST from intermediate device -> firewall or LB
# RST with window size 0 -> connection abort
# RST in response to SYN -> port filtered/rejected
```

### Connection Establishment Failure

```bash
# 1. DNS resolution
dig +short target_hostname

# 2. TCP port reachability
nc -zv target_ip port -w 5

# 3. If SYN sent but no SYN-ACK:
tcpdump -i eth0 -nn 'host target_ip and port PORT' -c 20
# See SYN going out but no SYN-ACK -> firewall/SG blocking or server not listening

# 4. If SYN-ACK received but connection still fails:
# Check if RST follows -> firewall rule that allows SYN but blocks data
# Check if application hangs after connect -> TLS handshake issue or app bug

# 5. SSL/TLS debugging
openssl s_client -connect target_ip:443 -servername hostname
# Shows: certificate chain, protocol version, cipher negotiation

# 6. Time breakdown
curl -o /dev/null -w "dns: %{time_namelookup}s\nconnect: %{time_connect}s\ntls: %{time_appconnect}s\nttfb: %{time_starttransfer}s\ntotal: %{time_total}s\n" https://target
```
