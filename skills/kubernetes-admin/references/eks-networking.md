# EKS Networking Deep Dive

## VPC CNI Plugin (aws-node)

The Amazon VPC CNI plugin assigns real VPC IP addresses to pods, making them first-class
citizens in the VPC network. This is fundamentally different from overlay networks used
by other CNI plugins (Calico, Flannel, Weave).

### How It Works

1. Each EC2 instance has a primary ENI (Elastic Network Interface)
2. The CNI plugin attaches secondary ENIs to the instance
3. Each ENI gets multiple secondary private IP addresses
4. Each pod gets one of these secondary IPs as its pod IP
5. Pods can communicate directly with any VPC resource (no encapsulation overhead)

### Checking CNI Status

```bash
# Check aws-node DaemonSet status
kubectl get daemonset aws-node -n kube-system

# Check aws-node pods on each node
kubectl get pods -n kube-system -l k8s-app=aws-node -o wide

# Check CNI logs for errors
kubectl logs -n kube-system -l k8s-app=aws-node --tail=50

# Check ENI allocation on a node (from the node)
curl http://169.254.169.254/latest/meta-data/network/interfaces/macs/

# Check available IPs in the warm pool
kubectl get node NODE -o jsonpath='{.metadata.annotations}' | python3 -m json.tool | grep vpc
```

### Common VPC CNI Issues

| Issue | Symptom | Diagnosis | Fix |
|-------|---------|-----------|-----|
| IP exhaustion | Pods stuck in Pending, "failed to assign an IP address" | `kubectl logs aws-node` shows "no available IP" | Expand subnet CIDR or enable prefix delegation |
| ENI limit reached | New pods cannot get IPs | Check instance type ENI limit | Use larger instance type or prefix delegation |
| Security group mismatch | Pods cannot reach services | Check SG associated with ENI | Update SG rules for pod traffic |
| Stale IP addresses | Pod has IP but no connectivity | Check aws-node reconciliation | Restart aws-node on affected node |
| Subnet has no free IPs | Node cannot create new ENIs | `aws ec2 describe-subnets` check AvailableIpAddressCount | Add new subnet to the VPC |

## Secondary IP Allocation

### ENI and IP Limits by Instance Type

The number of pods per node is limited by: (Number of ENIs * IPs per ENI) - 1

| Instance Type | Max ENIs | IPs per ENI | Max Pods (default) |
|--------------|----------|-------------|-------------------|
| t3.small | 3 | 4 | 11 |
| t3.medium | 3 | 6 | 17 |
| t3.large | 3 | 12 | 35 |
| m5.large | 3 | 10 | 29 |
| m5.xlarge | 4 | 15 | 58 |
| m5.2xlarge | 4 | 15 | 58 |
| m5.4xlarge | 8 | 30 | 234 |
| c5.large | 3 | 10 | 29 |
| c5.xlarge | 4 | 15 | 58 |
| r5.large | 3 | 10 | 29 |

```bash
# Check the max pods limit for your instance type
kubectl get node NODE -o jsonpath='{.status.allocatable.pods}'

# Check current pod count on a node
kubectl get pods --field-selector spec.nodeName=NODE --all-namespaces | wc -l

# Check ENI allocation via aws-node
kubectl exec -n kube-system $(kubectl get pod -n kube-system -l k8s-app=aws-node -o name | head -1) -- /opt/cni/bin/aws-cni-support.sh 2>/dev/null
```

## Prefix Delegation

Prefix delegation assigns /28 prefixes (16 IPs) to ENI slots instead of individual IPs.
This dramatically increases pod density.

### Enabling Prefix Delegation

```bash
# Enable prefix delegation on the aws-node DaemonSet
kubectl set env daemonset aws-node -n kube-system ENABLE_PREFIX_DELEGATION=true

# Set the max-pods limit on nodes to take advantage of higher density
# For managed node groups, use a launch template with:
# --kubelet-extra-args '--max-pods=110'

# Verify prefix delegation is active
kubectl logs -n kube-system -l k8s-app=aws-node | grep -i prefix
```

### Pod Density with Prefix Delegation

| Instance Type | Without PD | With PD |
|--------------|-----------|---------|
| t3.medium | 17 | 110 |
| m5.large | 29 | 110 |
| m5.xlarge | 58 | 110 |
| m5.4xlarge | 234 | 250 |

**Important considerations:**
- Subnet must have /28 blocks available (fragmentation can be an issue)
- Security groups for pods feature is NOT compatible with prefix delegation
- Prefix delegation works best with new, unfragmented subnets

## Custom Networking

Custom networking allows pods to use a different subnet/security group than the node.
This is useful when node subnets are small but pod subnets are large.

### Configuration

```bash
# Enable custom networking
kubectl set env daemonset aws-node -n kube-system AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG=true

# Create ENIConfig for each AZ
cat <<EOF | kubectl apply -f -
apiVersion: crd.k8s.amazonaws.com/v1alpha1
kind: ENIConfig
metadata:
  name: us-east-1a
spec:
  securityGroups:
    - sg-0123456789abcdef0
  subnet: subnet-0123456789abcdef0
---
apiVersion: crd.k8s.amazonaws.com/v1alpha1
kind: ENIConfig
metadata:
  name: us-east-1b
spec:
  securityGroups:
    - sg-0123456789abcdef0
  subnet: subnet-0fedcba9876543210
EOF

# Annotate nodes to use ENIConfig matching their AZ
kubectl set env daemonset aws-node -n kube-system ENI_CONFIG_LABEL_DEF=topology.kubernetes.io/zone
```

**When to use custom networking:**
- Node subnet is /24 (256 IPs) but you need hundreds of pods
- You want pods in a different subnet for security isolation
- You need different security groups for pods vs nodes

## Security Groups for Pods

Allows individual pods to have their own VPC security groups, providing network isolation
at the VPC level rather than just Kubernetes NetworkPolicy level.

### Prerequisites

- EKS cluster version 1.25+
- Nitro-based EC2 instances (m5, c5, r5, etc. -- NOT t2, t3)
- VPC CNI version 1.11+ with `ENABLE_POD_ENI=true`
- NOT compatible with prefix delegation

### Configuration

```bash
# Enable security groups for pods
kubectl set env daemonset aws-node -n kube-system ENABLE_POD_ENI=true

# Create a SecurityGroupPolicy
cat <<EOF | kubectl apply -f -
apiVersion: vpcresources.k8s.aws/v1beta1
kind: SecurityGroupPolicy
metadata:
  name: db-access-policy
  namespace: production
spec:
  podSelector:
    matchLabels:
      role: db-client
  securityGroups:
    groupIds:
      - sg-0123456789abcdef0  # allows access to RDS
      - sg-0fedcba9876543210  # base pod security group
EOF

# Verify pod got the security group
kubectl describe pod POD | grep "vpc.amazonaws.com/pod-eni"
```

### Limitations

- Reduces max pods per node (uses trunk ENIs)
- Windows pods not supported
- Not compatible with prefix delegation
- Pod startup is slightly slower (ENI attachment)

## Calico Network Policies

While EKS uses the VPC CNI for networking, you can install Calico for NetworkPolicy
enforcement (VPC CNI does not implement Kubernetes NetworkPolicy by itself).

### Installing Calico on EKS

```bash
# Install Calico for policy enforcement only (not as CNI)
kubectl apply -f https://raw.githubusercontent.com/aws/amazon-vpc-cni-k8s/master/config/master/calico-operator.yaml
kubectl apply -f https://raw.githubusercontent.com/aws/amazon-vpc-cni-k8s/master/config/master/calico-crs.yaml

# Verify Calico is running
kubectl get pods -n calico-system
```

### Network Policy Examples

```yaml
# Deny all ingress to a namespace (default deny)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Ingress

# Allow ingress from specific namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-monitoring
  namespace: production
spec:
  podSelector: {}
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
  policyTypes:
    - Ingress

# Allow specific port from specific pods
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-api-to-db
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: database
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: api-server
      ports:
        - protocol: TCP
          port: 5432
  policyTypes:
    - Ingress
```

## AWS Load Balancer Controller

The AWS Load Balancer Controller manages ALBs and NLBs for Kubernetes Services and
Ingress resources.

### ALB Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip          # pod IPs directly
    alb.ingress.kubernetes.io/healthcheck-path: /health
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443}]'
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:...
spec:
  rules:
    - host: myapp.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: myapp
                port:
                  number: 80
```

### NLB Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: myapp-nlb
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: external
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
    service.beta.kubernetes.io/aws-load-balancer-scheme: internet-facing
spec:
  type: LoadBalancer
  selector:
    app: myapp
  ports:
    - port: 443
      targetPort: 8443
      protocol: TCP
```

### Target Type: IP vs Instance

| Feature | IP Target | Instance Target |
|---------|-----------|-----------------|
| Traffic path | LB -> Pod IP directly | LB -> NodePort -> Pod |
| Performance | Lower latency (no extra hop) | Slightly higher latency |
| Requirement | VPC CNI (pods have VPC IPs) | Any CNI |
| Health checks | Direct to pod | Via NodePort |
| Pod readiness | Respects pod readiness gates | NodePort always accepts |

### Troubleshooting Load Balancer Controller

```bash
# Check controller pods
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller

# Check controller logs
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller --tail=100

# Check Ingress status (should show ALB address)
kubectl get ingress -n NAMESPACE

# Check target group health
aws elbv2 describe-target-health --target-group-arn TARGET_GROUP_ARN

# Common issues:
# 1. No ALB created -> check IAM permissions on controller service account
# 2. Targets unhealthy -> check healthcheck-path annotation matches app
# 3. 502 errors -> targets not ready, check pod readiness probes
# 4. Slow registration -> pods need readinessGates for ALB target group
```

## Pod Density Limits

Calculating the maximum number of pods per node is critical for capacity planning.

### Formula

```
Max pods = (Number of ENIs * (IPs per ENI - 1)) + 2

Where:
- "- 1" accounts for the primary IP of each ENI (used by the node, not pods)
- "+ 2" accounts for kube-proxy and aws-node pods using host networking
```

### Checking Current Density

```bash
# Max pods allowed on a node
kubectl get node NODE -o jsonpath='{.status.allocatable.pods}'

# Current pods on a node
kubectl get pods --all-namespaces --field-selector spec.nodeName=NODE --no-headers | wc -l

# Available capacity
echo "$(kubectl get node NODE -o jsonpath='{.status.allocatable.pods}') - $(kubectl get pods --all-namespaces --field-selector spec.nodeName=NODE --no-headers | wc -l)" | bc

# Cluster-wide pod density summary
kubectl get nodes -o custom-columns='NAME:.metadata.name,CAPACITY:.status.capacity.pods,ALLOCATABLE:.status.allocatable.pods'
```

### Increasing Pod Density

1. **Prefix delegation**: 16 IPs per ENI slot instead of 1 (see above)
2. **Larger instance types**: More ENIs and IPs per ENI
3. **Custom max-pods**: Override via kubelet `--max-pods` flag (in launch template)
4. **Custom networking**: Use larger subnets for pod IPs

**Warning:** Increasing max-pods beyond the ENI/IP limit will cause pods to fail to
get IP addresses. Always ensure subnet capacity matches the pod density target.
