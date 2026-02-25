#!/usr/bin/env bash
# Chaos: Deploy a stress-ng pod to consume CPU and memory on the node.
# Usage: bash resource-stress.sh [start|stop]
set -euo pipefail

NAMESPACE="chaos-lab"
ACTION="${1:-}"

case "${ACTION}" in
    start)
        echo "Deploying stress-ng pod (1.5 CPU, 768Mi memory, 10 min duration)..."
        kubectl apply -n "${NAMESPACE}" -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: stress-test
  namespace: chaos-lab
  labels:
    app: stress-test
    chaos: resource-stress
spec:
  containers:
    - name: stress
      image: alexeiled/stress-ng:latest
      args:
        - "--cpu"
        - "2"
        - "--vm"
        - "1"
        - "--vm-bytes"
        - "768M"
        - "--timeout"
        - "600"
        - "--metrics-brief"
      resources:
        requests:
          cpu: "1500m"
          memory: 768Mi
        limits:
          cpu: "2000m"
          memory: 1Gi
  restartPolicy: Never
  terminationGracePeriodSeconds: 5
EOF
        echo ""
        echo "Stress pod deployed. It will auto-terminate after 10 minutes."
        echo "Expected alarms (5-10 min): NodeCPU-High, NodeMemory-High"
        echo ""
        echo "Stop early with: bash resource-stress.sh stop"
        ;;

    stop)
        echo "Deleting stress-test pod..."
        kubectl delete pod stress-test -n "${NAMESPACE}" --force --grace-period=0 2>/dev/null || true
        echo "Stress pod removed."
        ;;

    *)
        echo "Usage: bash resource-stress.sh [start|stop]"
        echo ""
        echo "  start - Deploy stress-ng pod (1.5 CPU, 768Mi, 10min timeout)"
        echo "  stop  - Delete stress pod immediately"
        exit 1
        ;;
esac
