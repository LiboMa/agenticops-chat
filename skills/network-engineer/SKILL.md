---
name: network-engineer
description: "CCIE-level network engineering troubleshooting — covers routing, switching, firewall analysis, VPN diagnostics, load balancing, MTU analysis, TCP/IP diagnostics, and AWS VPC networking. Includes decision trees for connectivity failures, latency issues, packet loss, and DNS problems."
metadata:
  author: agenticops
  version: "1.0"
  domain: networking
---

# Network Engineer Skill

## Quick Decision Trees

### Connectivity Failure

1. Verify local interface: `ip addr show` — check UP state and IP assignment
2. Default gateway: `ip route show default` — verify gateway reachable
3. `ping -c 3 gateway_ip` — L3 connectivity to gateway
4. `traceroute -n target` or `mtr -n --report target` — find where packets drop
5. DNS: `dig +short target_hostname` — if fails, try `dig @8.8.8.8 target_hostname`
6. Firewall: `iptables -L -n -v` (host) + check AWS SG/NACL rules
7. MTU: `ping -M do -s 1472 -c 1 target` — if fails, MTU issue (try smaller sizes)

**Escalation path:**

```
Cannot reach target
  |
  +-- Can reach gateway?
  |     +-- No -> Interface/L2 issue
  |     |        +-- ip link show — is interface UP?
  |     |        +-- ethtool eth0 — link detected?
  |     |        +-- ARP table: ip neigh show — gateway MAC resolved?
  |     +-- Yes -> L3/routing issue
  |           +-- traceroute -n target — where does it die?
  |           +-- If dies at first hop -> default route wrong or next-hop down
  |           +-- If dies mid-path -> transit network issue
  |           +-- If reaches target but no response -> firewall/SG blocking
  |
  +-- Can resolve DNS?
  |     +-- No -> DNS tree
  |     +-- Yes but wrong IP -> stale DNS, check TTL
  |
  +-- Can reach IP but not port?
        +-- telnet target_ip port / nc -zv target_ip port
        +-- SG/NACL/iptables blocking?
        +-- Service not listening? (ss -tuln on target)
```

### Latency Issues

1. Baseline: `ping -c 20 target` — check avg/stddev
2. Hop-by-hop: `mtr -n --report -c 100 target` — identify high-latency hop
3. If within AWS: check inter-AZ vs cross-region latency patterns
4. TCP latency: `curl -o /dev/null -w "time_connect: %{time_connect}\ntime_ttfb: %{time_starttransfer}\n" https://target`
5. DNS latency: `dig target | grep "Query time"`
6. If intermittent: `mtr -n -c 500 target` — look for packet loss correlation

**Escalation path:**

```
Latency > expected baseline
  |
  +-- Consistent or intermittent?
  |     +-- Consistent -> Routing/path issue, MTU, congestion
  |     +-- Intermittent -> Buffer bloat, microbursts, TCP retransmits
  |
  +-- Where in the path?
  |     +-- First hop -> Local network (check duplex, errors)
  |     +-- Middle hops -> ISP/transit (often nothing you can control)
  |     +-- Last hop -> Target host or its network
  |
  +-- Application layer?
  |     +-- time_connect high -> Network latency
  |     +-- time_ttfb high but time_connect low -> Server processing slow
  |     +-- DNS resolution slow -> DNS tree
  |
  +-- AWS-specific?
        +-- Same AZ: < 1ms expected
        +-- Cross-AZ: 1-2ms expected
        +-- Cross-region: varies by distance (us-east-1 to eu-west-1 ~ 80ms)
        +-- Check placement groups for latency-sensitive workloads
```

### Packet Loss

1. `mtr -n --report -c 200 target` — loss at which hop?
2. If loss at final hop only -> host issue (firewall/rate limiting ICMP)
3. If loss at intermediate hop -> ISP/network issue
4. Check interface errors: `ip -s link show eth0` — look for RX/TX errors, drops
5. Ring buffer: `ethtool -g eth0` — check if ring buffer full
6. TCP retransmits: `ss -ti` — look for retrans count
7. `netstat -s | grep -i "retransmit\|error\|drop\|overflow"`

**Escalation path:**

```
Packet loss detected
  |
  +-- ICMP loss only? (TCP works fine)
  |     +-- Rate-limited ICMP on intermediate routers (normal)
  |     +-- Only trust mtr loss at final destination
  |
  +-- TCP retransmits?
  |     +-- Check: ss -ti dst target_ip
  |     +-- High retrans -> real packet loss in path
  |     +-- Window shrinking -> congestion response
  |
  +-- Interface level?
  |     +-- RX drops -> Ring buffer overflow or CPU cannot keep up
  |     +-- TX drops -> Egress queue full or rate limiting
  |     +-- RX errors -> Physical/driver issue
  |     +-- Overruns -> CPU interrupt handling too slow
  |
  +-- AWS-specific?
        +-- Bandwidth exceeded -> Throttled (check instance type limits)
        +-- PPS limit exceeded -> Check network PPS allowance
        +-- SG tracking limit -> conntrack table full
```

**Key metrics:**

```bash
# Interface error counters
ip -s link show eth0

# TCP retransmit rate
cat /proc/net/snmp | grep Tcp
# RetransSegs / OutSegs = retransmit ratio (> 1% is concerning)

# Socket-level retransmits
ss -ti | grep retrans

# NIC-level stats (driver-specific)
ethtool -S eth0 | grep -i "drop\|error\|miss\|timeout\|fifo"
```

### DNS Problems

1. `cat /etc/resolv.conf` — check nameserver configuration
2. `dig target_hostname` — check all response sections
3. `dig @specific_dns target_hostname` — test specific resolver
4. TTL issues: `dig +nocmd target_hostname | grep -v "^$\|^;"` — check TTL values
5. NXDOMAIN: verify domain exists with `dig +trace target_hostname`
6. Slow resolution: `dig target_hostname` — check Query time, if >100ms investigate resolver

**Escalation path:**

```
DNS resolution failing or slow
  |
  +-- No response from resolver?
  |     +-- Is resolver reachable? ping nameserver_ip
  |     +-- Is it port 53? nc -zvu nameserver_ip 53
  |     +-- Firewall blocking UDP 53 or TCP 53?
  |     +-- VPC DNS: check enableDnsSupport + enableDnsHostnames on VPC
  |
  +-- NXDOMAIN (domain not found)?
  |     +-- dig +trace — walk the delegation chain
  |     +-- Check if domain is in a Route 53 private hosted zone
  |     +-- Check search domain in resolv.conf
  |
  +-- SERVFAIL?
  |     +-- Upstream authoritative server issue
  |     +-- DNSSEC validation failure
  |     +-- Try: dig +cd target (disable DNSSEC checking)
  |
  +-- Slow resolution?
        +-- Local cache miss: first query slow, subsequent fast
        +-- Resolver overloaded: all queries slow
        +-- AWS VPC DNS limit: 1024 packets/s per interface
        +-- Consider Route 53 Resolver endpoints for hybrid DNS
```

### AWS VPC Networking

1. Security Groups: check inbound/outbound rules for protocol + port + source/dest
2. NACLs: check both inbound AND outbound (stateless!) — rule evaluation order matters
3. Route Tables: verify destination CIDR -> target (IGW, NAT, TGW, Peering, VPC Endpoint)
4. NAT Gateway: check in public subnet, has EIP, route table points to it
5. Transit Gateway: check TGW route tables, attachments, propagations
6. VPC Peering: check accepter/requester route tables both updated
7. VPC Endpoints: check route table entries, SG on endpoint, policy document

**Systematic VPC connectivity check:**

```
Source instance -> Target
  |
  +-- 1. Source SG outbound allows traffic?
  |        Protocol + Port + Destination CIDR/SG
  |
  +-- 2. Source subnet NACL outbound allows?
  |        Lowest numbered matching rule wins
  |        Remember: ephemeral port range (1024-65535) for return traffic
  |
  +-- 3. Source route table has route to destination?
  |        Most specific CIDR match wins
  |        local route (VPC CIDR) always takes priority
  |
  +-- 4. If cross-VPC: peering/TGW attachment + route exists?
  |
  +-- 5. Target subnet NACL inbound allows?
  |
  +-- 6. Target SG inbound allows?
  |        Protocol + Port + Source CIDR/SG
  |
  +-- 7. Target service listening on that port?
  |
  +-- 8. Return path: same checks in reverse
         (SG is stateful — return is automatic)
         (NACL is STATELESS — must allow return explicitly!)
```

## TCP/IP Diagnostic Commands

### TCP Connection Analysis

```bash
# Active established connections
ss -tn state established

# Connection state summary
ss -s

# SYN floods detection
ss -tn state syn-recv | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head

# Time-wait connections (many = high connection churn)
ss -tn state time-wait | wc -l

# Listen queue overflow (connections dropped before accept)
ss -tn state syn-recv | wc -l

# Connection details with timer info
ss -tn -o state established

# Connections to specific port
ss -tn '( dport = :443 or sport = :443 )'

# Socket buffer sizes
ss -tm    # show memory usage per socket
```

### Socket Buffer Tuning

```bash
# Current settings
sysctl net.core.rmem_default    # default receive buffer
sysctl net.core.rmem_max        # max receive buffer
sysctl net.core.wmem_default    # default send buffer
sysctl net.core.wmem_max        # max send buffer
sysctl net.ipv4.tcp_rmem        # TCP auto-tune: min default max
sysctl net.ipv4.tcp_wmem        # TCP auto-tune: min default max

# For high-bandwidth connections
sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.wmem_max=16777216
sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"

# Connection tracking table (important for NAT/firewall)
sysctl net.netfilter.nf_conntrack_max
cat /proc/net/nf_conntrack | wc -l    # current entries
# If near max: connection drops, "nf_conntrack: table full" in dmesg
sysctl -w net.netfilter.nf_conntrack_max=262144
```

### Packet Capture

```bash
# Basic capture on interface
tcpdump -i eth0 -nn host target_ip

# Specific port
tcpdump -i eth0 -nn port 443

# Write to pcap file for Wireshark analysis
tcpdump -i eth0 -nn -w /tmp/capture.pcap -c 1000

# TCP flags filter — SYN and RST packets
tcpdump -i eth0 -nn 'tcp[tcpflags] & (tcp-syn|tcp-rst) != 0'

# TCP retransmissions (rough detection)
tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn != 0' -c 100

# DNS queries only
tcpdump -i eth0 -nn port 53

# HTTP requests (unencrypted)
tcpdump -i eth0 -nn -A port 80 | grep -E "^(GET|POST|PUT|DELETE|HEAD)"

# Capture with ring buffer (long-running)
tcpdump -i eth0 -nn -w /tmp/cap.pcap -C 100 -W 10
# 10 files of 100MB each, rotating

# Read pcap file
tcpdump -nn -r /tmp/capture.pcap

# BPF filter for specific CIDR
tcpdump -i eth0 -nn net 10.0.1.0/24
```

### MTU and Path MTU Discovery

```bash
# Check interface MTU
ip link show eth0 | grep mtu

# Test path MTU (don't fragment flag)
ping -M do -s 1472 -c 1 target    # 1472 + 28 (IP+ICMP headers) = 1500
# If fails: "message too long" -> MTU < 1500 in path

# Binary search for path MTU
ping -M do -s 1400 -c 1 target    # try smaller
ping -M do -s 1450 -c 1 target    # narrow down

# AWS-specific MTU:
# Standard: 1500 bytes
# Jumbo frames (within VPC, same AZ, supported instances): 9001 bytes
# VPN/TGW/Internet: 1500 bytes
# GRE/VXLAN tunnels: overhead reduces effective MTU

# PMTU caching
ip route get target_ip    # shows cached PMTU
ip route show cache       # all cached routes with PMTU
```

## Load Balancer Diagnostics

### AWS ALB/NLB Troubleshooting

```
Target returning 5xx errors
  |
  +-- ALB 502 (Bad Gateway)
  |     +-- Target closed connection before response
  |     +-- Target returned malformed response
  |     +-- Check: target health, connection timeout settings
  |
  +-- ALB 503 (Service Unavailable)
  |     +-- No healthy targets in target group
  |     +-- Check: target group health check status
  |
  +-- ALB 504 (Gateway Timeout)
  |     +-- Target did not respond within idle timeout
  |     +-- Default: 60 seconds
  |     +-- Check: ALB idle timeout vs application response time
  |
  +-- NLB TCP resets
        +-- Flow idle timeout (350s for TCP)
        +-- Target deregistration (draining timeout)
        +-- Client sends to NLB after flow expired
```

### Health Check Debugging

```bash
# Simulate ALB health check from target
curl -v http://localhost:PORT/health-check-path

# Check from ALB's perspective
aws elbv2 describe-target-health \
  --target-group-arn arn:aws:elasticloadbalancing:...

# Common health check failures:
# 1. Health check path returns non-200
# 2. Health check timeout exceeded
# 3. Security group on target doesn't allow health check port
# 4. NACL blocking health check (remember: stateless!)
# 5. Application not listening on health check port
```

## VPN Diagnostics

### IPSec/Site-to-Site VPN

```
VPN tunnel down
  |
  +-- Phase 1 (IKE) failing?
  |     +-- Check: pre-shared key match
  |     +-- Check: IKE version (v1 vs v2)
  |     +-- Check: encryption/hash/DH group match
  |     +-- Check: peer IP reachable (port 500/UDP, port 4500/UDP for NAT-T)
  |     +-- AWS: check CGW IP matches actual public IP
  |
  +-- Phase 2 (IPSec) failing?
  |     +-- Check: interesting traffic CIDR match
  |     +-- Check: encryption/hash/PFS group match
  |     +-- Check: lifetime mismatch (AWS default: 3600s)
  |
  +-- Tunnel up but no traffic?
        +-- Route table missing route to remote CIDR via VGW/TGW
        +-- SG/NACL blocking traffic
        +-- Remote side not routing back to VPC CIDR
        +-- Asymmetric routing (traffic goes out one tunnel, returns other)
```

### AWS VPN Monitoring

```bash
# Check tunnel status
aws ec2 describe-vpn-connections \
  --vpn-connection-ids vpn-xxx \
  --query 'VpnConnections[].VgwTelemetry[]'

# CloudWatch metrics for VPN
# TunnelState: 0=down, 1=up
# TunnelDataIn / TunnelDataOut: bytes
```

## Common Network Tuning Parameters

```bash
# TCP keepalive (detect dead connections)
sysctl net.ipv4.tcp_keepalive_time=60       # seconds before first probe (default: 7200)
sysctl net.ipv4.tcp_keepalive_intvl=10      # seconds between probes
sysctl net.ipv4.tcp_keepalive_probes=6      # probes before declaring dead

# SYN flood protection
sysctl net.ipv4.tcp_syncookies=1            # enable SYN cookies
sysctl net.ipv4.tcp_max_syn_backlog=8192    # SYN queue size

# TIME_WAIT recycling
sysctl net.ipv4.tcp_tw_reuse=1              # reuse TIME_WAIT for outgoing connections
# Note: tcp_tw_recycle was removed in kernel 4.12 (broke NAT)

# Connection tracking
sysctl net.netfilter.nf_conntrack_max=262144
sysctl net.netfilter.nf_conntrack_tcp_timeout_established=86400

# Ring buffer (increase to reduce drops under load)
ethtool -G eth0 rx 4096 tx 4096

# Interrupt coalescing (reduce CPU at cost of small latency increase)
ethtool -C eth0 rx-usecs 100 tx-usecs 100
```

## Tool Reference Quick Card

| Tool | Purpose | Key Flags |
|------|---------|-----------|
| `ip` | Network config | `addr show`, `route show`, `-s link`, `neigh show` |
| `ss` | Socket stats | `-tuln` (listen), `-s` (summary), `-ti` (TCP info) |
| `ping` | ICMP connectivity | `-c N`, `-M do -s SIZE` (MTU test) |
| `traceroute` | Path trace | `-n` (no DNS), `-T` (TCP mode), `-I` (ICMP) |
| `mtr` | Combined ping+traceroute | `-n --report -c 100` (batch report) |
| `dig` | DNS lookup | `+short`, `+trace`, `@server`, `+nocmd` |
| `nslookup` | DNS lookup (simpler) | `nslookup host server` |
| `tcpdump` | Packet capture | `-nn` (no resolve), `-w file`, `-i iface` |
| `curl` | HTTP diagnostics | `-v`, `-o /dev/null -w "format"`, `--connect-timeout` |
| `nc` (netcat) | Port test / raw TCP | `-zv host port` (scan), `-l -p port` (listen) |
| `ethtool` | NIC diagnostics | `-g` (ring), `-S` (stats), `-i` (driver) |
| `iptables` | Firewall rules | `-L -n -v`, `-t nat -L -n` |
| `conntrack` | Connection tracking | `-L` (list), `-S` (stats), `-C` (count) |
| `iftop` | Bandwidth monitor | `-i eth0`, `-n` (no resolve) |
| `nload` | Bandwidth graph | `nload eth0` |
| `iperf3` | Bandwidth test | `-s` (server), `-c host` (client), `-P N` (parallel) |
| `arping` | ARP-level ping | `-I eth0 target_ip` |
| `bridge` | Bridge/VLAN | `link show`, `vlan show` |
