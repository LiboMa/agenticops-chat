#!/usr/bin/env bash
# Chaos: Break deployment via bad image or invalid config.
# Usage: bash config-break.sh [bad-image|bad-config|restore]
set -euo pipefail

NAMESPACE="chaos-lab"
ACTION="${1:-}"

case "${ACTION}" in
    bad-image)
        echo "Setting frontend image to non-existent tag..."
        kubectl set image deployment/frontend \
            -n "${NAMESPACE}" \
            nginx=nginx:99.99-nonexistent
        echo ""
        echo "Frontend pods will enter ImagePullBackOff / ErrImagePull state."
        echo "Expected alarms (5 min): PodRestarts-High"
        echo ""
        echo "Detection path: list_alarms → PodRestarts-High → query_logs (ImagePullBackOff)"
        echo ""
        echo "Restore with: bash config-break.sh restore"
        ;;

    bad-config)
        echo "Pushing invalid nginx config..."
        kubectl create configmap nginx-config \
            -n "${NAMESPACE}" \
            --from-literal=default.conf='invalid { config syntax !!!;' \
            --dry-run=client -o yaml | kubectl apply -f -
        echo ""
        echo "Restarting frontend deployment to pick up broken config..."
        kubectl rollout restart deployment/frontend -n "${NAMESPACE}"
        echo ""
        echo "Frontend pods will crash on startup (nginx config parse error)."
        echo "Expected alarms (5 min): PodRestarts-High, RunningPods-Low"
        echo ""
        echo "Detection path: list_alarms → PodRestarts-High → query_logs (CrashLoopBackOff)"
        echo ""
        echo "Restore with: bash config-break.sh restore"
        ;;

    restore)
        echo "Restoring frontend image to nginx:1.25-alpine..."
        kubectl set image deployment/frontend \
            -n "${NAMESPACE}" \
            nginx=nginx:1.25-alpine

        echo "Restoring valid nginx ConfigMap..."
        kubectl apply -f "$(cd "$(dirname "${BASH_SOURCE[0]}")/../workloads" && pwd)/configmap.yaml"

        echo "Restarting frontend deployment..."
        kubectl rollout restart deployment/frontend -n "${NAMESPACE}"

        echo ""
        echo "Waiting for rollout..."
        kubectl rollout status deployment/frontend -n "${NAMESPACE}" --timeout=120s
        echo ""
        kubectl get pods -n "${NAMESPACE}" -l app=frontend
        ;;

    *)
        echo "Usage: bash config-break.sh [bad-image|bad-config|restore]"
        echo ""
        echo "  bad-image  - Set frontend image to nginx:99.99-nonexistent"
        echo "  bad-config - Replace nginx config with invalid syntax"
        echo "  restore    - Restore correct image and config"
        exit 1
        ;;
esac
