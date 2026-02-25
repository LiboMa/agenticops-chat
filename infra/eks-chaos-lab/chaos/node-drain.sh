#!/usr/bin/env bash
# Chaos: Drain a node to simulate node failure.
# Usage: bash node-drain.sh [drain|restore]
set -euo pipefail

ACTION="${1:-}"

get_first_node() {
    kubectl get nodes -o jsonpath='{.items[0].metadata.name}'
}

case "${ACTION}" in
    drain)
        NODE=$(get_first_node)
        echo "Target node: ${NODE}"
        echo ""
        echo "Cordoning node (preventing new pod scheduling)..."
        kubectl cordon "${NODE}"
        echo ""
        echo "Draining node (evicting pods with 60s grace period)..."
        kubectl drain "${NODE}" \
            --ignore-daemonsets \
            --delete-emptydir-data \
            --force \
            --grace-period=60 \
            --timeout=120s
        echo ""
        echo "Node ${NODE} is drained and cordoned."
        echo "Expected alarms (2-5 min): NodeCount-Low, RunningPods-Low"
        echo ""
        echo "Restore with: bash node-drain.sh restore"
        ;;

    restore)
        echo "Uncordoning all nodes..."
        for NODE in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
            echo "  Uncordoning ${NODE}"
            kubectl uncordon "${NODE}"
        done
        echo ""
        echo "All nodes are schedulable again."
        echo "Pods will be rescheduled automatically."
        echo ""
        sleep 5
        kubectl get nodes
        echo ""
        kubectl get pods -n chaos-lab -o wide
        ;;

    *)
        echo "Usage: bash node-drain.sh [drain|restore]"
        echo ""
        echo "  drain   - Cordon and drain the first node"
        echo "  restore - Uncordon all nodes"
        exit 1
        ;;
esac
