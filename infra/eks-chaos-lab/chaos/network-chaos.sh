#!/usr/bin/env bash
# Chaos: Block network traffic to the backend using a NetworkPolicy.
# Usage: bash network-chaos.sh [block|restore]
set -euo pipefail

NAMESPACE="chaos-lab"
ACTION="${1:-}"

case "${ACTION}" in
    block)
        echo "Applying NetworkPolicy to block all ingress to backend..."
        kubectl apply -n "${NAMESPACE}" -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: chaos-block-backend
  namespace: chaos-lab
  labels:
    chaos: network-block
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Ingress
  ingress: []
EOF
        echo ""
        echo "NetworkPolicy applied — all ingress to backend pods is blocked."
        echo "Frontend → backend connections will fail (connection refused / timeout)."
        echo ""
        echo "Detection path: describe_load_balancers → unhealthy targets → query_logs"
        echo ""
        echo "Restore with: bash network-chaos.sh restore"
        ;;

    restore)
        echo "Deleting chaos NetworkPolicy..."
        kubectl delete networkpolicy chaos-block-backend -n "${NAMESPACE}" 2>/dev/null || true
        echo "NetworkPolicy removed — backend ingress restored."
        ;;

    *)
        echo "Usage: bash network-chaos.sh [block|restore]"
        echo ""
        echo "  block   - Apply NetworkPolicy blocking all ingress to backend"
        echo "  restore - Remove the chaos NetworkPolicy"
        exit 1
        ;;
esac
