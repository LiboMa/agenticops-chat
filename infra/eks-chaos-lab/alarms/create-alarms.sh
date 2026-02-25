#!/usr/bin/env bash
# Create 6 CloudWatch alarms for the EKS chaos lab cluster.
# Uses ContainerInsights and AWS/EKS metric namespaces.
set -euo pipefail

CLUSTER_NAME="${1:-agenticops-chaos-lab}"
REGION="${2:-us-east-1}"
PREFIX="EKS-${CLUSTER_NAME}"

echo "Creating CloudWatch alarms for cluster: ${CLUSTER_NAME} in ${REGION}"
echo ""

# 1. Node CPU High
echo "  [1/6] ${PREFIX}-NodeCPU-High"
aws cloudwatch put-metric-alarm \
    --region "${REGION}" \
    --alarm-name "${PREFIX}-NodeCPU-High" \
    --alarm-description "EKS node CPU utilization >80% for 10 minutes" \
    --namespace ContainerInsights \
    --metric-name node_cpu_utilization \
    --dimensions Name=ClusterName,Value="${CLUSTER_NAME}" \
    --statistic Average \
    --period 300 \
    --evaluation-periods 2 \
    --threshold 80 \
    --comparison-operator GreaterThanThreshold \
    --treat-missing-data missing \
    --tags Key=Project,Value=agenticops Key=Environment,Value=chaos-lab

# 2. Node Memory High
echo "  [2/6] ${PREFIX}-NodeMemory-High"
aws cloudwatch put-metric-alarm \
    --region "${REGION}" \
    --alarm-name "${PREFIX}-NodeMemory-High" \
    --alarm-description "EKS node memory utilization >80% for 10 minutes" \
    --namespace ContainerInsights \
    --metric-name node_memory_utilization \
    --dimensions Name=ClusterName,Value="${CLUSTER_NAME}" \
    --statistic Average \
    --period 300 \
    --evaluation-periods 2 \
    --threshold 80 \
    --comparison-operator GreaterThanThreshold \
    --treat-missing-data missing \
    --tags Key=Project,Value=agenticops Key=Environment,Value=chaos-lab

# 3. Pod Restarts High
echo "  [3/6] ${PREFIX}-PodRestarts-High"
aws cloudwatch put-metric-alarm \
    --region "${REGION}" \
    --alarm-name "${PREFIX}-PodRestarts-High" \
    --alarm-description "EKS pod container restarts >5 in 5 minutes" \
    --namespace ContainerInsights \
    --metric-name pod_number_of_container_restarts \
    --dimensions Name=ClusterName,Value="${CLUSTER_NAME}" Name=Namespace,Value=chaos-lab \
    --statistic Sum \
    --period 300 \
    --evaluation-periods 1 \
    --threshold 5 \
    --comparison-operator GreaterThanThreshold \
    --treat-missing-data missing \
    --tags Key=Project,Value=agenticops Key=Environment,Value=chaos-lab

# 4. Running Pods Low
echo "  [4/6] ${PREFIX}-RunningPods-Low"
aws cloudwatch put-metric-alarm \
    --region "${REGION}" \
    --alarm-name "${PREFIX}-RunningPods-Low" \
    --alarm-description "EKS running pods <3 for 2 minutes" \
    --namespace ContainerInsights \
    --metric-name pod_number_of_running_pods \
    --dimensions Name=ClusterName,Value="${CLUSTER_NAME}" Name=Namespace,Value=chaos-lab \
    --statistic Average \
    --period 60 \
    --evaluation-periods 2 \
    --threshold 3 \
    --comparison-operator LessThanThreshold \
    --treat-missing-data missing \
    --tags Key=Project,Value=agenticops Key=Environment,Value=chaos-lab

# 5. API Server High Latency
echo "  [5/6] ${PREFIX}-APIServer-HighLatency"
aws cloudwatch put-metric-alarm \
    --region "${REGION}" \
    --alarm-name "${PREFIX}-APIServer-HighLatency" \
    --alarm-description "EKS API server p99 latency >1s for 5 minutes" \
    --namespace ContainerInsights \
    --metric-name apiserver_request_duration_seconds \
    --dimensions Name=ClusterName,Value="${CLUSTER_NAME}" \
    --extended-statistic p99 \
    --period 300 \
    --evaluation-periods 1 \
    --threshold 1 \
    --comparison-operator GreaterThanThreshold \
    --treat-missing-data missing \
    --tags Key=Project,Value=agenticops Key=Environment,Value=chaos-lab

# 6. Node Count Low
echo "  [6/6] ${PREFIX}-NodeCount-Low"
aws cloudwatch put-metric-alarm \
    --region "${REGION}" \
    --alarm-name "${PREFIX}-NodeCount-Low" \
    --alarm-description "EKS cluster node count <2 for 2 minutes" \
    --namespace ContainerInsights \
    --metric-name cluster_node_count \
    --dimensions Name=ClusterName,Value="${CLUSTER_NAME}" \
    --statistic Average \
    --period 60 \
    --evaluation-periods 2 \
    --threshold 2 \
    --comparison-operator LessThanThreshold \
    --treat-missing-data missing \
    --tags Key=Project,Value=agenticops Key=Environment,Value=chaos-lab

echo ""
echo "All 6 alarms created. Verify with:"
echo "  aws cloudwatch describe-alarms --alarm-name-prefix ${PREFIX} \\"
echo "    --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}' --output table"
