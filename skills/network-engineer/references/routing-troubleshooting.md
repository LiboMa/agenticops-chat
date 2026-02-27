# Routing Troubleshooting Reference

## Route Table Evaluation Order

Linux evaluates routes using longest prefix match (most specific route wins):

```bash
# View full routing table
ip route show

# View routing table for a specific destination
ip route get 10.0.5.100

# View all routing tables (if policy routing is in use)
ip rule show
ip route show table main
ip route show table 254    # main table number
```

### Route Selection Algorithm

```
1. Longest prefix match (most specific CIDR wins)
   - /32 > /24 > /16 > /8 > /0 (default)

2. If same prefix length: metric (lower = preferred)
   - ip route add 10.0.0.0/8 via 10.1.1.1 metric 100
   - ip route add 10.0.0.0/8 via 10.2.2.1 metric 200
   -> First route preferred

3. If same metric: protocol preference
   - connected > static > BGP > OSPF (depends on admin distance)

4. Scope: link < host < global
```

### AWS Route Table Specifics

```
AWS route evaluation:
1. Local route (VPC CIDR) — ALWAYS highest priority, cannot be overridden
2. Longest prefix match among remaining routes
3. For same prefix:
   - Static routes preferred over propagated routes
   - If both propagated: lower AS path length wins (BGP)

Key constraints:
- Cannot route to overlapping CIDRs (except local route)
- Local route covers entire VPC CIDR — traffic within VPC stays within VPC
- NAT Gateway: route 0.0.0.0/0 -> nat-xxx (for private subnets)
- Internet Gateway: route 0.0.0.0/0 -> igw-xxx (for public subnets)
- Transit Gateway: specific CIDRs -> tgw-xxx (for cross-VPC)
```

### Common Route Issues

```bash
# Missing default route
ip route show default
# If empty: no default gateway configured
# Fix: ip route add default via GATEWAY_IP dev eth0

# Blackhole route (packets silently dropped)
ip route show | grep blackhole
# AWS uses blackhole for unresolved TGW routes

# Unreachable route (ICMP unreachable returned)
ip route show | grep unreachable

# Multiple default routes (split brain)
ip route show default
# If multiple: check metrics, unexpected path selection
```

## BGP (Border Gateway Protocol)

### BGP State Machine

```
Idle -> Connect -> OpenSent -> OpenConfirm -> Established
  |        |          |            |
  |        v          v            v
  +---- Active     (errors)     (errors)
         (retry)     -> Idle      -> Idle

States:
  Idle        — BGP process initialized, waiting for start event
  Connect     — TCP connection attempt in progress (port 179)
  Active      — TCP connection attempt failed, retrying
  OpenSent    — TCP connected, OPEN message sent, waiting for peer OPEN
  OpenConfirm — OPEN received, KEEPALIVE sent, waiting for peer KEEPALIVE
  Established — Peers exchanging routes (this is the goal state)
```

### BGP Troubleshooting

```
BGP peer not reaching Established state
  |
  +-- Stuck in Idle?
  |     +-- BGP not started or peer IP misconfigured
  |     +-- Check: can reach peer IP? (ping peer_ip)
  |     +-- Firewall blocking TCP 179?
  |
  +-- Stuck in Active/Connect?
  |     +-- TCP connection failing
  |     +-- Port 179 blocked (firewall, SG, NACL)
  |     +-- Peer IP not reachable at L3
  |     +-- Wrong peer IP configured on either side
  |
  +-- Stuck in OpenSent?
  |     +-- OPEN message rejected by peer
  |     +-- AS number mismatch
  |     +-- BGP identifier (router-id) conflict
  |     +-- Capability negotiation failure
  |
  +-- Stuck in OpenConfirm?
  |     +-- KEEPALIVE not received
  |     +-- Holdtime mismatch (must be 0 or >= 3s on both sides)
  |
  +-- Established but no routes?
        +-- No matching prefix lists/route maps
        +-- Prefix advertised but filtered
        +-- AS path loop (own AS in path)
        +-- Next-hop unreachable
```

### AWS BGP (VPN + Direct Connect)

```bash
# Check BGP status for VPN connection
aws ec2 describe-vpn-connections \
  --vpn-connection-ids vpn-xxx \
  --query 'VpnConnections[].VgwTelemetry[].{Status:Status,StatusMessage:StatusMessage}'

# Direct Connect BGP status
aws directconnect describe-virtual-interfaces \
  --query 'virtualInterfaces[].{Id:virtualInterfaceId,BGPPeers:bgpPeers}'

# AWS VPN uses BGP with ASN:
# Default AWS side: 64512 (configurable on VGW/TGW)
# Customer side: your ASN (private: 64512-65534, or public)

# Route propagation: enable on route table
aws ec2 enable-vgw-route-propagation \
  --route-table-id rtb-xxx \
  --gateway-id vgw-xxx

# Check propagated routes
aws ec2 describe-route-tables --route-table-ids rtb-xxx \
  --query 'RouteTables[].Routes[?Origin==`EnableVgwRoutePropagation`]'
```

## OSPF (Open Shortest Path First)

### OSPF Neighbor States

```
Down -> Attempt -> Init -> 2-Way -> ExStart -> Exchange -> Loading -> Full
                                ^
                                |
                             (DR/BDR election happens at 2-Way)

States:
  Down     — No Hello received from neighbor
  Attempt  — Hello sent (NBMA networks only), no response
  Init     — Hello received, but own router ID not in neighbor's Hello
  2-Way    — Bidirectional communication confirmed (see own ID in neighbor Hello)
             DR/BDR election occurs here (broadcast/NBMA)
  ExStart  — Master/slave negotiation for database exchange
  Exchange — Database Description (DBD) packets exchanged
  Loading  — LSAs being requested and received
  Full     — Databases synchronized — adjacency formed
```

### OSPF Troubleshooting

```
OSPF adjacency not forming
  |
  +-- Stuck in Init?
  |     +-- Unidirectional communication
  |     +-- ACL blocking OSPF (protocol 89)
  |     +-- Multicast 224.0.0.5/6 blocked
  |     +-- MTU mismatch (won't go past ExStart)
  |
  +-- Stuck in 2-Way?
  |     +-- Normal for DROther-to-DROther on broadcast segments
  |     +-- Only DR/BDR form Full adjacency with others
  |
  +-- Stuck in ExStart/Exchange?
  |     +-- MTU mismatch (most common cause)
  |     +-- Check: ip ospf mtu-ignore (workaround)
  |
  +-- Parameter mismatches that prevent adjacency:
        +-- Area ID must match
        +-- Hello/Dead intervals must match (10/40 default)
        +-- Network type must match (broadcast, point-to-point, etc.)
        +-- Authentication must match (type + key)
        +-- Stub area flags must match
```

## Transit Gateway (TGW) Routing

### TGW Route Table Architecture

```
TGW has its own route tables, separate from VPC route tables:

VPC Route Table         TGW Route Table         VPC Route Table
  10.1.0.0/16 local       10.1.0.0/16 -> att-vpc1   10.2.0.0/16 local
  10.2.0.0/16 -> tgw      10.2.0.0/16 -> att-vpc2   10.1.0.0/16 -> tgw
  0.0.0.0/0 -> nat-gw     0.0.0.0/0 -> att-egress   0.0.0.0/0 -> nat-gw

Flow: VPC1 -> VPC route table -> TGW -> TGW route table -> VPC2
```

### TGW Troubleshooting

```bash
# List TGW route tables
aws ec2 describe-transit-gateway-route-tables \
  --transit-gateway-id tgw-xxx

# Search routes in a TGW route table
aws ec2 search-transit-gateway-routes \
  --transit-gateway-route-table-id tgw-rtb-xxx \
  --filters "Name=type,Values=static,propagated"

# Check attachment associations
aws ec2 get-transit-gateway-route-table-associations \
  --transit-gateway-route-table-id tgw-rtb-xxx

# Check propagations
aws ec2 get-transit-gateway-route-table-propagations \
  --transit-gateway-route-table-id tgw-rtb-xxx

# Common issues:
# 1. VPC attachment not associated with correct TGW route table
# 2. Route propagation not enabled for attachment
# 3. VPC route table missing route to TGW for remote CIDRs
# 4. Blackhole routes in TGW table (attachment deleted but route remains)
# 5. Overlapping CIDRs between VPCs (ambiguous routing)
```

## Asymmetric Routing Detection

Asymmetric routing occurs when packets take different paths for forward and return traffic:

```
Symptoms:
- TCP connections fail (SYN goes path A, SYN-ACK returns path B)
- Stateful firewalls drop return traffic (no matching session)
- Intermittent connectivity (works sometimes depending on path selection)

Detection:
1. traceroute from both sides — compare paths
2. tcpdump on suspected middle devices:
   - See SYN but no SYN-ACK on device A
   - See SYN-ACK but no SYN on device B
   -> Traffic is asymmetric

3. AWS-specific:
   - Multiple route tables with different default routes
   - VPN with 2 tunnels and no BGP (manual routes may conflict)
   - Cross-AZ NAT Gateway (source in AZ-a, NAT-GW in AZ-b, return goes to AZ-b)

Fix:
- Ensure symmetric route tables (both directions use same path)
- Use BGP with consistent metrics
- AWS: use NAT Gateway in same AZ as source instances
- Disable stateful inspection if asymmetric is intentional (rare)
```

## Route Propagation and Redistribution

### VPC Route Propagation

```bash
# Enable route propagation from VGW to route table
aws ec2 enable-vgw-route-propagation \
  --route-table-id rtb-xxx \
  --gateway-id vgw-xxx

# Check propagation status
aws ec2 describe-route-tables \
  --route-table-ids rtb-xxx \
  --query 'RouteTables[].PropagatingVgws'

# Propagated routes appear with Origin: "EnableVgwRoutePropagation"
# Static routes take precedence over propagated routes for same CIDR
```

### Policy-Based Routing (Linux)

```bash
# View routing rules
ip rule show

# Add policy route (mark-based)
iptables -t mangle -A PREROUTING -s 10.0.1.0/24 -j MARK --set-mark 100
ip rule add fwmark 100 table custom_table
ip route add default via 10.0.2.1 table custom_table

# Add policy route (source-based)
ip rule add from 10.0.1.0/24 table custom_table
ip route add default via 10.0.2.1 table custom_table

# Verify
ip route get 8.8.8.8 from 10.0.1.5
# Shows which route table and next-hop will be used
```

## Troubleshooting Workflows

### Complete Connectivity Debug (L1 to L7)

```bash
# Layer 1 (Physical/Link)
ethtool eth0 | grep "Link detected"
ip link show eth0 | grep "state UP"

# Layer 2 (Data Link)
ip neigh show                        # ARP table
arping -I eth0 gateway_ip            # ARP-level reachability

# Layer 3 (Network)
ip addr show eth0                    # IP address assigned?
ip route get target_ip               # route exists?
ping -c 3 target_ip                  # ICMP reachability

# Layer 4 (Transport)
nc -zv target_ip 443                 # TCP port open?
nc -zuv target_ip 53                 # UDP port open?
ss -tn dst target_ip                 # existing connections?

# Layer 7 (Application)
curl -v https://target               # full HTTP exchange
curl -o /dev/null -w "%{http_code} %{time_total}s\n" https://target
```

### VPC Flow Log Analysis

```bash
# Flow log format (default):
# version account-id interface-id srcaddr dstaddr srcport dstport protocol packets bytes start end action log-status

# Find rejected traffic to specific IP
# In CloudWatch Logs Insights:
# fields @timestamp, srcaddr, dstaddr, srcport, dstport, action
# | filter dstaddr = "10.0.1.50" and action = "REJECT"
# | sort @timestamp desc
# | limit 50

# Or in S3/Athena:
# SELECT srcaddr, dstaddr, dstport, action, COUNT(*) as hits
# FROM vpc_flow_logs
# WHERE action = 'REJECT' AND dstaddr = '10.0.1.50'
# GROUP BY srcaddr, dstaddr, dstport, action
# ORDER BY hits DESC
# LIMIT 20

# Protocol numbers:
# 1 = ICMP, 6 = TCP, 17 = UDP
```
