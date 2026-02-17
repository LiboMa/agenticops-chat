---
resource_type: VPC
issue_pattern: connectivity_failure
severity: high
keywords: [vpc, connectivity, security group, nacl, route table, blackhole, nat gateway, subnet, ip exhaustion, peering, transit gateway, network]
---

# VPC Connectivity Issues - Standard Operating Procedure

## Symptoms
- Application cannot reach downstream services or databases
- Timeout errors from resources within VPC
- Intermittent connectivity failures between subnets or VPCs
- NAT Gateway errors (port allocation, packet drops)
- Subnet IP address exhaustion (AvailableIpAddressCount = 0)
- Cross-VPC communication failures (peering/TGW)

## Diagnostic Steps

1. **Check Security Group Rules**: Call describe_security_groups for the affected resource's SG.
   - Verify inbound rules allow traffic from the source CIDR or security group.
   - Verify outbound rules allow traffic to the destination.
   - Common mistake: allowing inbound but forgetting outbound (non-default SG).

2. **Check Network ACLs**: NACLs are stateless — both inbound AND outbound rules must allow traffic.
   - Deny rules are evaluated before allow rules (rule number ordering).
   - Ephemeral port range (1024-65535) must be open for return traffic.

3. **Check Route Tables**: Call describe_route_tables for the VPC.
   - Look for routes in "blackhole" state — this means the target (NAT GW, TGW, VPC peering) was deleted but the route remains.
   - Verify the subnet has a route to the destination (0.0.0.0/0 for internet, specific CIDR for peering).
   - Verify the correct route table is associated with the subnet.

4. **Check NAT Gateway**: Call describe_nat_gateways if private subnets need internet access.
   - State must be "available". States: pending, failed, available, deleting, deleted.
   - Check CloudWatch: ErrorPortAllocation (port exhaustion), PacketsDropCount.
   - NAT GW has a limit of 55,000 simultaneous connections per destination.

5. **Check Subnet IP Exhaustion**: Call describe_subnets.
   - AvailableIpAddressCount near 0 means new ENIs/instances cannot launch.
   - AWS reserves 5 IPs per subnet (first 4 + last 1).

6. **Check VPC Peering / Transit Gateway**: Call describe_transit_gateways.
   - Peering: both VPCs must have routes pointing to the peering connection.
   - TGW: check attachment state is "available", route table has propagated routes.
   - Cross-account: verify the attachment is accepted (not pending-acceptance).

## Common Root Causes
- **Security Group misconfiguration**: Missing inbound/outbound rule for the required port/protocol
- **NACL deny rule**: Explicit deny blocking traffic (rule evaluated before allow)
- **Route table blackhole**: Target resource (NAT GW, TGW, peering) deleted without cleaning routes
- **NAT Gateway failure**: NAT GW in "failed" state or port allocation exhaustion
- **Subnet IP exhaustion**: No available IP addresses for new network interfaces
- **DNS resolution failure**: VPC DNS settings disabled (enableDnsSupport / enableDnsHostnames)
- **TGW route missing**: Transit Gateway route table not propagating routes from attachment

## Resolution

1. **Security Group fix**: Add the missing rule (protocol, port range, source/destination).
2. **NACL fix**: Add allow rule with lower rule number than the deny, or remove the deny rule.
3. **Blackhole route**: Delete the blackhole route and create a new route pointing to a valid target.
4. **NAT Gateway recovery**: If failed, create a new NAT GW in the same subnet. Update route tables.
5. **IP exhaustion**: Expand subnet CIDR (if VPC allows) or move workloads to a larger subnet.
6. **TGW routing**: Add static route or enable route propagation in the TGW route table.

## Prevention
- Use VPC Flow Logs to monitor rejected traffic patterns
- Set CloudWatch alarms on NAT Gateway ErrorPortAllocation and PacketsDropCount
- Monitor subnet AvailableIpAddressCount with threshold alerts
- Use AWS Config rules to detect security group changes
- Implement infrastructure as code (CloudFormation/Terraform) for route table management
