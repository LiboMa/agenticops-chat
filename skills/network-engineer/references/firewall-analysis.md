# Firewall Analysis Reference

## iptables Architecture

### Chain Processing Order

```
Incoming packet:
  PREROUTING (raw -> mangle -> nat)
    |
    +-- Destination is local? -> INPUT (mangle -> filter -> security -> nat)
    |                                    |
    |                                    v
    |                              Local Process
    |                                    |
    |                              OUTPUT (raw -> mangle -> nat -> filter -> security)
    |                                    |
    |                                    v
    |                              POSTROUTING (mangle -> nat)
    |
    +-- Destination is other? -> FORWARD (mangle -> filter -> security)
                                         |
                                         v
                                   POSTROUTING (mangle -> nat)
```

### Key Chains for Troubleshooting

| Chain | Table | Purpose | When |
|-------|-------|---------|------|
| INPUT | filter | Traffic TO this host | After routing decision |
| OUTPUT | filter | Traffic FROM this host | After local process |
| FORWARD | filter | Traffic THROUGH this host | Routing between interfaces |
| PREROUTING | nat | DNAT (destination NAT) | Before routing decision |
| POSTROUTING | nat | SNAT/MASQUERADE | After routing decision |

### Viewing iptables Rules

```bash
# Show all filter rules with counters
iptables -L -n -v
# -L: list rules
# -n: numeric (no DNS resolution)
# -v: verbose (show counters, interfaces)

# Show specific chain
iptables -L INPUT -n -v --line-numbers

# Show NAT rules
iptables -t nat -L -n -v

# Show mangle rules (packet marking, TOS)
iptables -t mangle -L -n -v

# Show raw rules (connection tracking exemptions)
iptables -t raw -L -n -v

# Show rules as iptables commands (for backup/restore)
iptables-save

# Show rules for specific table as commands
iptables-save -t filter
```

### Rule Evaluation

```
Rules are evaluated TOP TO BOTTOM in each chain.
First matching rule wins (for terminal targets like ACCEPT, DROP, REJECT).
Non-terminal targets (LOG, MARK) continue processing.

Chain policy (default action) applies if no rule matches.

# Check chain policy
iptables -L INPUT | head -1
# Chain INPUT (policy ACCEPT)  <- default if no rules match
# Chain INPUT (policy DROP)    <- secure default

# Rule matching:
# Each rule has conditions (source, dest, protocol, port, state, etc.)
# If ALL conditions match, the target action is taken
# If ANY condition doesn't match, the next rule is evaluated
```

### Common iptables Patterns

```bash
# Allow established connections (must be near top of INPUT chain)
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Allow SSH from specific CIDR
iptables -A INPUT -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT

# Allow HTTP/HTTPS from anywhere
iptables -A INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT

# Rate-limit SSH connections (anti-brute-force)
iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW \
  -m recent --set --name SSH
iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW \
  -m recent --update --seconds 60 --hitcount 4 --name SSH -j DROP

# Log dropped packets (before DROP rule)
iptables -A INPUT -j LOG --log-prefix "IPTABLES-DROP: " --log-level 4
iptables -A INPUT -j DROP

# Check logs
journalctl -k | grep "IPTABLES-DROP"
dmesg | grep "IPTABLES-DROP"
```

## Connection Tracking (conntrack)

iptables uses conntrack to maintain state for stateful firewall rules:

```bash
# View connection tracking table
conntrack -L
# Output: protocol, timeout, state, src/dst/sport/dport for both directions

# Connection tracking statistics
conntrack -S
# entries:       current entries in table
# searched:      hash table lookups
# found:         successful lookups
# new:           new entries created
# invalid:       packets not matching any entry
# insert_failed: table full, cannot insert
# drop:          packets dropped due to table full

# Count current entries
conntrack -C

# Check maximum
sysctl net.netfilter.nf_conntrack_max

# If table full: "nf_conntrack: table full, dropping packet" in dmesg
# Fix:
sysctl -w net.netfilter.nf_conntrack_max=262144

# Clear specific entries
conntrack -D -d 10.0.1.50    # delete entries to destination
conntrack -D -p tcp --dport 80    # delete entries to port 80
```

### conntrack States

| State | Description |
|-------|-------------|
| NEW | First packet of connection (SYN for TCP) |
| ESTABLISHED | Packets in both directions seen |
| RELATED | New connection related to ESTABLISHED (FTP data, ICMP error) |
| INVALID | Packet doesn't match any known connection or is malformed |

## AWS Security Groups (Stateful)

### Key Properties

```
Security Groups are STATEFUL:
- If inbound rule allows traffic IN, response is automatically allowed OUT
- If outbound rule allows traffic OUT, response is automatically allowed IN
- No need to create matching inbound+outbound rules

Evaluation:
- ALL rules are evaluated (not ordered like NACLs)
- Default: deny all inbound, allow all outbound
- Can only ALLOW rules (no explicit DENY)
- Changes take effect immediately (no save/apply needed)
- Applied at ENI level (instance network interface)
```

### SG Troubleshooting

```bash
# View SG rules
aws ec2 describe-security-groups --group-ids sg-xxx

# Check which SGs are attached to an instance
aws ec2 describe-instances --instance-ids i-xxx \
  --query 'Reservations[].Instances[].SecurityGroups'

# Check which SGs are attached to an ENI
aws ec2 describe-network-interfaces --network-interface-ids eni-xxx \
  --query 'NetworkInterfaces[].Groups'

# Common SG issues:
# 1. Source/destination mismatch
#    - Rule allows sg-abc but traffic comes from sg-xyz
#    - Rule allows 10.0.0.0/16 but source is 10.1.0.0/16

# 2. Protocol/port mismatch
#    - Rule allows TCP 443 but application uses TCP 8443
#    - Rule allows TCP but application uses UDP

# 3. SG-to-SG references with peering
#    - Cross-VPC SG references require peering connection
#    - Cannot reference SG in different region

# 4. Multiple SGs on one ENI
#    - Union of all rules applies (most permissive wins)
#    - Max 5 SGs per ENI (adjustable quota)

# 5. Outbound rules forgotten
#    - Default allows all outbound, but if customized...
#    - Must allow outbound to target for connection initiation
```

### SG Limits and Quotas

```
Default limits (per region):
- SGs per VPC: 2500
- Rules per SG: 60 inbound + 60 outbound
- SGs per ENI: 5
- Rules evaluated per ENI: SGs * rules = max 300 per direction

If you hit limits:
- Combine SGs (use prefix lists for multiple CIDRs)
- Use managed prefix lists (count as 1 rule regardless of entries)
- Request quota increase via AWS Support
```

## AWS NACLs (Stateless)

### Key Properties

```
NACLs are STATELESS:
- Must explicitly allow BOTH inbound AND outbound traffic
- Must allow ephemeral ports (1024-65535) for return traffic
- Rules are NUMBERED and evaluated in ORDER (lowest first)
- First matching rule wins (then STOP evaluating)
- Default NACL allows all; custom NACLs deny all by default
- Applied at SUBNET level (all instances in subnet affected)
```

### NACL Rule Evaluation

```
Example NACL (inbound):
  Rule 100: ALLOW TCP 443 from 0.0.0.0/0
  Rule 200: DENY  TCP 443 from 10.0.0.0/8
  Rule *:   DENY  all from 0.0.0.0/0 (default)

Traffic from 10.0.1.5 to port 443:
  -> Matches Rule 100 (ALLOW) -> ALLOWED
  -> Rule 200 never evaluated!

Fix: Move DENY rule to lower number:
  Rule 50:  DENY  TCP 443 from 10.0.0.0/8
  Rule 100: ALLOW TCP 443 from 0.0.0.0/0
```

### Common NACL Misconfigurations

```
1. Forgetting ephemeral port range on outbound:
   Inbound: ALLOW TCP 443 from 0.0.0.0/0
   Outbound: ALLOW TCP 443 to 0.0.0.0/0    <- WRONG!

   Client connects FROM ephemeral port (e.g., 49152) TO port 443
   Response goes FROM port 443 TO ephemeral port 49152
   Outbound must allow: TCP 1024-65535 to 0.0.0.0/0

2. Forgetting NACL is per-subnet:
   Instance A (subnet-1) -> Instance B (subnet-2)
   Must check:
   - subnet-1 NACL outbound allows traffic to B
   - subnet-2 NACL inbound allows traffic from A
   - subnet-2 NACL outbound allows response to A (ephemeral ports)
   - subnet-1 NACL inbound allows response from B (ephemeral ports)

3. NACL blocking health checks:
   ALB in subnet-1 sends health check to target in subnet-2
   subnet-2 NACL must allow inbound from ALB subnet CIDR on health check port
   subnet-2 NACL must allow outbound ephemeral ports to ALB subnet CIDR
```

### NACL Troubleshooting Commands

```bash
# View NACL rules
aws ec2 describe-network-acls --network-acl-ids acl-xxx

# Find NACL for a subnet
aws ec2 describe-network-acls \
  --filters "Name=association.subnet-id,Values=subnet-xxx"

# Check both inbound and outbound
aws ec2 describe-network-acls --network-acl-ids acl-xxx \
  --query 'NetworkAcls[].Entries[?RuleAction==`deny`]'
```

## NLB vs ALB Security Group Requirements

### ALB (Application Load Balancer)

```
ALB has its own SG:
  Inbound:  Allow client traffic (e.g., TCP 443 from 0.0.0.0/0)
  Outbound: Allow health checks + traffic to targets

Target instances SG:
  Inbound:  Allow from ALB SG on target port (e.g., TCP 8080 from sg-alb)

This works because ALB terminates TCP connection and creates new one to target.
Traffic source IP on target = ALB private IP (use X-Forwarded-For for client IP).
```

### NLB (Network Load Balancer)

```
NLB behavior depends on target type:

Instance targets:
  - NLB preserves client source IP
  - Target SG must allow client CIDR (not NLB SG)
  - Health check source: NLB node IP in the AZ

IP targets:
  - Source IP = NLB node private IP (not client IP)
  - Target SG can use NLB node IPs or VPC CIDR
  - Use Proxy Protocol v2 to get client IP

NLB SG (if enabled, newer feature):
  Inbound:  Allow client traffic
  Outbound: Allow to targets
  Target SG: Can reference NLB SG (like ALB pattern)

NLB without SG (legacy):
  - No SG on NLB itself
  - Target SG must allow client IPs directly
  - Health check: allow from NLB subnet CIDRs
```

## Troubleshooting Workflows

### Firewall Rule Debugging

```bash
# 1. Identify current rules affecting traffic
iptables -L -n -v --line-numbers | grep PORT

# 2. Watch rule hit counters in real-time
watch -n 1 'iptables -L INPUT -n -v --line-numbers'
# Send test traffic and watch which rule counter increments

# 3. Add temporary LOG rule above DROP
iptables -I INPUT 1 -p tcp --dport PORT -j LOG --log-prefix "DEBUG: "
# Send test traffic
journalctl -k --since "1 minute ago" | grep "DEBUG"
# Remove LOG rule when done
iptables -D INPUT 1

# 4. Use conntrack to see if connection is being tracked
conntrack -L -p tcp --dport PORT

# 5. Check if traffic is reaching the host at all
tcpdump -i eth0 -nn port PORT -c 10
# If no packets: upstream firewall (SG, NACL, or network)
# If packets arrive but no response: local firewall (iptables)
```

### AWS SG/NACL Debugging

```bash
# 1. Use VPC Reachability Analyzer (preferred)
aws ec2 create-network-insights-path \
  --source eni-source \
  --destination eni-dest \
  --destination-port 443 \
  --protocol tcp

aws ec2 start-network-insights-analysis \
  --network-insights-path-id nip-xxx

aws ec2 describe-network-insights-analyses \
  --network-insights-analysis-ids nia-xxx

# 2. Check VPC Flow Logs for REJECT
# Filter for: action=REJECT, dstaddr=target, dstport=target_port

# 3. Systematic check (in order):
echo "1. Source SG outbound"
aws ec2 describe-security-groups --group-ids sg-source \
  --query 'SecurityGroups[].IpPermissionsEgress'

echo "2. Source NACL outbound"
aws ec2 describe-network-acls \
  --filters "Name=association.subnet-id,Values=subnet-source" \
  --query 'NetworkAcls[].Entries[?Egress==`true`]'

echo "3. Route table (source subnet)"
aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=subnet-source" \
  --query 'RouteTables[].Routes'

echo "4. Dest NACL inbound"
aws ec2 describe-network-acls \
  --filters "Name=association.subnet-id,Values=subnet-dest" \
  --query 'NetworkAcls[].Entries[?Egress==`false`]'

echo "5. Dest SG inbound"
aws ec2 describe-security-groups --group-ids sg-dest \
  --query 'SecurityGroups[].IpPermissions'
```

### nftables (iptables successor)

Modern Linux distributions are moving to nftables:

```bash
# List all rules
nft list ruleset

# List specific table
nft list table inet filter

# Equivalent to iptables -L -n -v
nft list chain inet filter input

# Add rule
nft add rule inet filter input tcp dport 443 accept

# Delete rule by handle
nft -a list chain inet filter input    # show handles
nft delete rule inet filter input handle 42

# Note: iptables commands often still work via iptables-nft translation layer
# Check: iptables -V
# "iptables v1.8.x (nf_tables)" = using nftables backend
```
