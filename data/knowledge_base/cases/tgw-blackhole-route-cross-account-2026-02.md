---
title: "Transit Gateway Blackhole Route Blocking Cross-Account VPC Connectivity"
resource_type: TransitGateway
severity: high
region: us-east-1
root_cause: missing_route_propagation
confidence: 0.92
date: 2026-02-05
tags: [transit-gateway, cross-account, blackhole, routing, vpc-peering]
---

# Transit Gateway Blackhole Route Blocking Cross-Account VPC Connectivity

## Symptoms
- Workloads in Account B's VPC (`vpc-0bbb1111`) cannot reach shared services (DNS, logging, monitoring) in Account A's VPC (`vpc-0aaa2222`)
- Ping and TCP connections from Account B instances to Account A IPs timeout
- Account A's shared services are accessible from Account A's own VPC and from Account C (another spoke account)
- Transit Gateway (`tgw-0abc1234`) shows the attachment for Account B as **available**
- VPC route tables in Account B correctly point the shared services CIDR (`10.0.0.0/16`) to the TGW

## Root Cause
When Account B's VPC was attached to the Transit Gateway, the TGW route table was updated with a **static route** for Account B's CIDR (`10.1.0.0/16`). However, the return path was never configured:

1. The TGW route table associated with Account B's attachment was missing route propagation for the shared services attachment (Account A)
2. Traffic from Account B to Account A reached the TGW successfully
3. The TGW forwarded traffic to Account A via the correct attachment
4. Return traffic from Account A entered the TGW but hit a **blackhole** route — the TGW route table had no route (propagated or static) for `10.1.0.0/16` pointing back to Account B's attachment
5. The route was visible in the TGW route table as state: `blackhole` because the propagation was never enabled

Running `aws ec2 search-transit-gateway-routes` confirmed:
```json
{
  "DestinationCidrBlock": "10.1.0.0/16",
  "State": "blackhole",
  "Type": "propagated"
}
```

## Resolution Steps
1. Identify the TGW route table associated with the shared services attachment:
   ```bash
   aws ec2 describe-transit-gateway-route-tables --filters Name=transit-gateway-id,Values=tgw-0abc1234
   ```
2. Enable route propagation for Account B's attachment on the TGW route table:
   ```bash
   aws ec2 enable-transit-gateway-route-table-propagation \
     --transit-gateway-route-table-id tgw-rtb-0shared \
     --transit-gateway-attachment-id tgw-attach-0bbb
   ```
3. Verify the route state changes from `blackhole` to `active`:
   ```bash
   aws ec2 search-transit-gateway-routes \
     --transit-gateway-route-table-id tgw-rtb-0shared \
     --filters Name=route-search.exact-match,Values=10.1.0.0/16
   ```
4. Test connectivity from Account B to Account A shared services
5. Verify bidirectional traffic flow with VPC Flow Logs on both sides

## Prevention
- Use route propagation (not static routes) for all TGW attachments to avoid manual route management errors
- Implement a TGW route table audit script that checks for `blackhole` routes on a schedule
- Use AWS Config rule `ec2-transit-gateway-route-table-check` (custom) to detect missing propagations
- Document the TGW onboarding checklist: attachment creation → route table association → route propagation enablement → connectivity test
- Use AWS RAM (Resource Access Manager) with proper automation to ensure consistent cross-account TGW setup

## Related
- Applies to any multi-account Transit Gateway architecture with spoke VPCs
- Similar blackhole issues can occur when a TGW attachment is deleted but the static route remains
- VPC peering has analogous issues when route table entries are missing in one direction
