#!/usr/bin/env bash
# Chaos: Kill pods or scale deployments to zero in the chaos-lab namespace.
# Usage: bash pod-kill.sh [kill|scale-zero|restore]
set -euo pipefail

NAMESPACE="chaos-lab"
ACTION="${1:-}"

case "${ACTION}" in
    kill)
        echo "Killing all frontend pods..."
        kubectl delete pods -n "${NAMESPACE}" -l app=frontend --force --grace-period=0
        echo ""
        echo "Pods killed. New pods will be recreated by the Deployment controller."
        echo "To prevent recreation, use 'scale-zero' instead."
        echo ""
        echo "Expected alarms (2-5 min): RunningPods-Low (briefly)"
        ;;

    scale-zero)
        echo "Scaling frontend to 0 replicas..."
        kubectl scale deployment frontend -n "${NAMESPACE}" --replicas=0
        echo "Scaling backend to 0 replicas..."
        kubectl scale deployment backend -n "${NAMESPACE}" --replicas=0
        echo ""
        echo "All workloads scaled to zero."
        echo "Expected alarms (2-5 min): RunningPods-Low"
        echo ""
        echo "Restore with: bash pod-kill.sh restore"
        ;;

    restore)
        echo "Restoring frontend to 3 replicas..."
        kubectl scale deployment frontend -n "${NAMESPACE}" --replicas=3
        echo "Restoring backend to 2 replicas..."
        kubectl scale deployment backend -n "${NAMESPACE}" --replicas=2
        echo ""
        echo "Waiting for pods to be ready..."
        kubectl rollout status deployment/frontend -n "${NAMESPACE}" --timeout=120s
        kubectl rollout status deployment/backend -n "${NAMESPACE}" --timeout=120s
        echo ""
        kubectl get pods -n "${NAMESPACE}"
        ;;

    *)
        echo "Usage: bash pod-kill.sh [kill|scale-zero|restore]"
        echo ""
        echo "  kill       - Force-delete all frontend pods (they will restart)"
        echo "  scale-zero - Scale all deployments to 0 replicas"
        echo "  restore    - Restore original replica counts (frontend=3, backend=2)"
        exit 1
        ;;
esac
