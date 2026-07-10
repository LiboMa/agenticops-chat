#!/usr/bin/env bash
# Evidence scenario: scale CoreDNS to 0 (cluster-wide DNS failure), and restore.
set -euo pipefail
ACTION="${1:-}"
case "${ACTION}" in
  break)
    kubectl scale deploy/coredns -n kube-system --replicas=0
    echo "CoreDNS scaled to 0 — DNS resolution will fail cluster-wide."
    ;;
  restore)
    kubectl scale deploy/coredns -n kube-system --replicas=2
    kubectl rollout status deploy/coredns -n kube-system --timeout=120s || true
    echo "CoreDNS restored to 2 replicas."
    ;;
  *) echo "Usage: coredns-down.sh [break|restore]"; exit 1;;
esac
