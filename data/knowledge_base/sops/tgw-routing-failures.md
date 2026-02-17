---
resource_type: TransitGateway
issue_pattern: routing_failure
severity: high
keywords: [transit gateway, tgw, routing, blackhole, attachment, cross-account, bgp, peering, vpc attachment, propagation]
---

# Transit Gateway Routing Failures - Standard Operating Procedure

## Symptoms
- Cross-VPC communication failures through Transit Gateway
- Packets dropped (PacketDropCountBlackhole in CloudWatch)
- VPC attachment in "pending" or "failed" state
- Asymmetric routing or unreachable destination CIDRs
- BGP session down for VPN attachments

## Diagnostic Steps

1. **Check TGW State**: Call describe_transit_gateways to verify TGW is in "available" state.
   - Review all attachments and their states.
   - "pendingAcceptance" means cross-account attachment awaiting acceptance.
   - "failed" means attachment creation failed (check CloudTrail for reason).

2. **Check TGW Route Table Associations**: Each attachment must be associated with a TGW route table.
   - Missing association means no routes will be evaluated for that attachment's traffic.

3. **Check TGW Route Table Propagation**: VPC attachments should propagate their CIDR routes.
   - If propagation is disabled, static routes must be manually added.
   - Missing propagation is the most common cause of cross-VPC unreachability.

4. **Check for Blackhole Routes**: Routes pointing to deleted or failed attachments become blackholes.
   - CloudWatch PacketDropCountBlackhole > 0 confirms this.
   - Check TGW route table for routes with state "blackhole".

5. **Check VPC Route Tables**: Each VPC must have a route pointing to the TGW for destination CIDRs.
   - Call describe_route_tables for each connected VPC.
   - Common mistake: VPC has a route to TGW for 10.0.0.0/8 but the specific /16 is missing.

6. **Check Cross-Account Attachments**: For cross-account TGW sharing via RAM.
   - Attachment must be accepted by the resource owner.
   - RAM share must include the correct principals.

## Common Root Causes
- **Missing route table association**: Attachment not associated with any TGW route table
- **Propagation disabled**: VPC CIDR not propagated to TGW route table
- **Blackhole routes**: Deleted attachment left orphaned routes
- **VPC route missing**: VPC subnet route table lacks route to TGW for target CIDR
- **Cross-account pending**: Attachment stuck in pendingAcceptance state
- **Overlapping CIDRs**: Two VPCs with overlapping CIDR ranges cause routing conflicts
- **BGP issues**: VPN attachment BGP session down (for hybrid connectivity)

## Resolution

1. **Missing association**: Associate the attachment with the correct TGW route table.
2. **Enable propagation**: Enable route propagation for the attachment in the TGW route table.
3. **Fix blackhole**: Delete the blackhole route. If the destination is still needed, create a new route pointing to a valid attachment.
4. **Add VPC route**: Add a route in the VPC subnet route table with the destination CIDR pointing to the TGW ID.
5. **Accept attachment**: Accept the cross-account attachment from the resource owner account.
6. **CIDR conflict**: Re-address one of the overlapping VPCs or use more specific routes.

## Prevention
- Enable default route table association and propagation on TGW creation
- Use AWS Config rules to detect route table changes
- Monitor PacketDropCountBlackhole with CloudWatch alarms
- Document network topology and CIDR allocations to prevent overlaps
- Use infrastructure as code for all TGW route table management
