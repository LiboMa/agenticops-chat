#!/bin/bash
# Case 11: DNS Poisoning Cascade — CoreDNS ConfigMap rewrite breaks redis-cart resolution
#
# Fault chain:
#   1. Patch CoreDNS ConfigMap: add "hosts" plugin that overrides redis-cart → 10.0.255.254
#   2. CoreDNS pods restart with poisoned config — CoreDNS stays HEALTHY
#   3. DNS TTL expires (~30s): cartservice new connections resolve redis-cart to wrong IP
#   4. cartservice → redis-cart: TCP connection timeout (10.0.255.254 is non-routable)
#   5. checkoutservice → cartservice: gRPC deadline exceeded (upstream timeout)
#   6. frontend → checkoutservice: HTTP 500 (checkout broken)
#   7. Alerts fire on frontend (HighErrorRate) and checkoutservice (HighLatencyP99)
#
# RCA challenge:
#   - ALL pods are Running/Ready — including CoreDNS and redis-cart
#   - Alerts fire on frontend and checkoutservice, NOT on the actual broken layer (DNS)
#   - KubeCoreDNSDown alert does NOT fire (CoreDNS is healthy, just returning wrong answers)
#   - CloudTrail has NO relevant events (K8s ConfigMap change, not AWS API)
#   - Redis-cart pod is perfectly healthy — direct IP connection works
#   - Agent must: follow traces → find cartservice redis timeout → check DNS resolution
#     → inspect CoreDNS ConfigMap → find the poisoned hosts entry
#   - Tests: distributed trace analysis, DNS-level diagnosis, K8s ConfigMap inspection
#
# Detection: Prometheus HighErrorRate on frontend + HighLatencyP99 on checkoutservice
# Recovery: Restore original CoreDNS ConfigMap
#
# Usage: bash inject.sh [inject|verify|recover]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

NAMESPACE="online-boutique"
COREDNS_NS="kube-system"
BACKUP_FILE="${SCRIPT_DIR}/original-coredns-configmap.yaml"

action="${1:-inject}"

case "$action" in
    inject)
        echo "=== Case 11: DNS Poisoning Cascade ==="

        # Pre-check
        echo ""
        echo "--- Pre-checks ---"
        echo "Frontend pods:"
        kubectl get pods -n "$NAMESPACE" -l app=frontend --no-headers
        echo ""
        echo "Redis-cart pods:"
        kubectl get pods -n "$NAMESPACE" -l app=redis-cart --no-headers
        echo ""
        echo "CoreDNS pods:"
        kubectl get pods -n "$COREDNS_NS" -l k8s-app=kube-dns --no-headers
        echo ""

        # DNS resolution before injection
        echo "DNS resolution (before):"
        kubectl exec -n "$NAMESPACE" deploy/cartservice -- \
            sh -c "nslookup redis-cart.${NAMESPACE}.svc.cluster.local 2>/dev/null | head -6" \
            2>/dev/null || echo "  (nslookup not available, trying getent)"
        kubectl exec -n "$NAMESPACE" deploy/cartservice -- \
            sh -c "getent hosts redis-cart.${NAMESPACE}.svc.cluster.local 2>/dev/null || echo 'getent not available'" \
            2>/dev/null || true
        echo ""

        # Get redis-cart ClusterIP for comparison
        REDIS_REAL_IP=$(kubectl get svc redis-cart -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}')
        echo "Redis-cart real ClusterIP: $REDIS_REAL_IP"
        echo ""

        # === Step 1: Backup original CoreDNS ConfigMap ===
        echo "Backing up CoreDNS ConfigMap..."
        kubectl get configmap coredns -n "$COREDNS_NS" -o yaml > "$BACKUP_FILE"
        echo "  Saved to: $BACKUP_FILE"

        # === Step 2: Inject DNS poison ===
        echo ""
        echo "Injecting DNS poison: redis-cart.${NAMESPACE}.svc.cluster.local → 10.0.255.254"

        # Use python to carefully patch the Corefile
        kubectl get configmap coredns -n "$COREDNS_NS" -o json | \
        python3 -c "
import json, sys, re

cm = json.load(sys.stdin)
corefile = cm['data']['Corefile']

# The poison: hosts plugin that overrides redis-cart to a non-routable IP
# Must be placed BEFORE the 'kubernetes' plugin so it takes priority
poison_block = '''    hosts {
        10.0.255.254 redis-cart.${NAMESPACE}.svc.cluster.local
        fallthrough
    }
'''

# Find the 'kubernetes' line and insert before it
if 'kubernetes ' in corefile:
    # Insert hosts block before kubernetes plugin
    corefile = corefile.replace(
        '    kubernetes ',
        poison_block + '    kubernetes '
    )
    cm['data']['Corefile'] = corefile
    json.dump(cm, sys.stdout)
else:
    print('ERROR: Could not find kubernetes plugin in Corefile', file=sys.stderr)
    sys.exit(1)
" | kubectl apply -f -

        echo "  CoreDNS ConfigMap patched."

        # === Step 3: Restart CoreDNS to pick up new config ===
        echo ""
        echo "Restarting CoreDNS pods to load poisoned config..."
        kubectl rollout restart deployment coredns -n "$COREDNS_NS"
        kubectl rollout status deployment coredns -n "$COREDNS_NS" --timeout=90s
        echo "  CoreDNS restarted and healthy."

        # === Step 4: Wait for DNS cache expiry + cascade ===
        echo ""
        echo "Waiting 45s for DNS cache expiry and cascade propagation..."
        sleep 45

        # === Step 5: Verify symptoms ===
        echo ""
        echo "=== Symptom Verification ==="

        echo ""
        echo "1. CoreDNS status (should be Running/Ready):"
        kubectl get pods -n "$COREDNS_NS" -l k8s-app=kube-dns --no-headers
        echo "   ^ CoreDNS is HEALTHY — this is NOT a crash scenario"

        echo ""
        echo "2. Redis-cart pod status (should be Running/Ready):"
        kubectl get pods -n "$NAMESPACE" -l app=redis-cart --no-headers
        echo "   ^ Redis-cart is HEALTHY — the pod works fine"

        echo ""
        echo "3. DNS resolution (POISONED):"
        kubectl exec -n "$NAMESPACE" deploy/cartservice -- \
            sh -c "getent hosts redis-cart.${NAMESPACE}.svc.cluster.local 2>/dev/null || \
                    nslookup redis-cart.${NAMESPACE}.svc.cluster.local 2>/dev/null | grep -i address" \
            2>/dev/null || echo "  Could not resolve (expected: 10.0.255.254)"
        echo "   Expected: 10.0.255.254 (poisoned). Real IP: $REDIS_REAL_IP"

        echo ""
        echo "4. Direct redis-cart connectivity (bypassing DNS):"
        kubectl exec -n "$NAMESPACE" deploy/cartservice -- \
            sh -c "nc -z -w2 $REDIS_REAL_IP 6379 && echo 'REACHABLE via direct IP' || echo 'UNREACHABLE'" \
            2>/dev/null || echo "  nc not available"

        echo ""
        echo "5. Cartservice logs (should show redis timeout):"
        kubectl logs -n "$NAMESPACE" deploy/cartservice --tail=10 2>/dev/null | \
            grep -i "redis\|timeout\|error\|connect" | tail -5 || echo "  (no redis errors yet)"

        echo ""
        echo "6. Frontend error check:"
        # Port-forward and test (if possible)
        FRONTEND_POD=$(kubectl get pods -n "$NAMESPACE" -l app=frontend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
        if [ -n "$FRONTEND_POD" ]; then
            kubectl exec -n "$NAMESPACE" "$FRONTEND_POD" -- \
                sh -c "wget -qO- --timeout=5 http://localhost:8080/ 2>&1 | head -1" \
                2>/dev/null || echo "  Frontend may be returning errors"
        fi

        echo ""
        echo "7. All pod restarts (check for cascade):"
        kubectl get pods -n "$NAMESPACE" --no-headers | awk '{if ($4+0 > 0) print "  " $1 " restarts=" $4}'

        echo ""
        echo "=== Fault Active ==="
        echo "CoreDNS is healthy but returning WRONG IP for redis-cart."
        echo "Cascade: DNS poison → cartservice timeout → checkout failure → frontend 5xx"
        echo ""
        echo "Alerts expected:"
        echo "  - HighErrorRate on frontend (5xx from checkout failures)"
        echo "  - HighLatencyP99 on checkoutservice (waiting for cartservice timeout)"
        echo "  - KubePodCrashLooping on cartservice (MAYBE, if it crashes on redis timeout)"
        echo "  - KubeCoreDNSDown: NO — CoreDNS is healthy!"
        echo ""
        echo "Agent must trace: frontend → checkoutservice → cartservice → DNS resolution → CoreDNS ConfigMap"
        echo ""
        echo "Run: bash $0 recover"
        ;;

    verify)
        echo "=== Verifying Case 11 ==="

        REDIS_REAL_IP=$(kubectl get svc redis-cart -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "unknown")

        echo "CoreDNS pods:"
        kubectl get pods -n "$COREDNS_NS" -l k8s-app=kube-dns
        echo ""

        echo "CoreDNS ConfigMap (check for poison):"
        kubectl get configmap coredns -n "$COREDNS_NS" -o yaml | grep -B1 -A5 "hosts" || echo "  No hosts block found (clean)"
        echo ""

        echo "DNS resolution from cartservice:"
        kubectl exec -n "$NAMESPACE" deploy/cartservice -- \
            sh -c "getent hosts redis-cart.${NAMESPACE}.svc.cluster.local 2>/dev/null || echo 'resolution failed'" \
            2>/dev/null || echo "  exec failed"
        echo "  Real redis-cart ClusterIP: $REDIS_REAL_IP"
        echo ""

        echo "Direct connectivity to redis-cart (bypassing DNS):"
        kubectl exec -n "$NAMESPACE" deploy/cartservice -- \
            sh -c "nc -z -w2 $REDIS_REAL_IP 6379 && echo 'REACHABLE' || echo 'UNREACHABLE'" \
            2>/dev/null || echo "  nc not available"
        echo ""

        echo "Cartservice logs (redis errors):"
        kubectl logs -n "$NAMESPACE" deploy/cartservice --tail=20 2>/dev/null | \
            grep -i "redis\|timeout\|error\|connect\|fail" | tail -10 || echo "  no errors"
        echo ""

        echo "Frontend pods:"
        kubectl get pods -n "$NAMESPACE" -l app=frontend
        echo ""

        echo "All pods with restarts:"
        kubectl get pods -n "$NAMESPACE" --no-headers | awk '{if ($4+0 > 0) print "  " $1 " restarts=" $4}'
        echo ""

        echo "Prometheus alerts (if reachable):"
        PROM_POD=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
        if [ -n "$PROM_POD" ]; then
            kubectl exec -n monitoring "$PROM_POD" -c prometheus -- \
                wget -qO- 'http://localhost:9090/api/v1/alerts' 2>/dev/null | \
                python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for alert in data.get('data', {}).get('alerts', []):
        name = alert.get('labels', {}).get('alertname', '?')
        state = alert.get('state', '?')
        svc = alert.get('labels', {}).get('service', alert.get('labels', {}).get('pod', ''))
        print(f'  {name}: {state} (service={svc})')
except: print('  Could not parse alerts')
" 2>/dev/null || echo "  Could not query Prometheus"
        fi
        ;;

    recover)
        echo "=== Recovering Case 11 ==="

        if [ -f "$BACKUP_FILE" ]; then
            echo "Restoring original CoreDNS ConfigMap from backup..."
            kubectl apply -f "$BACKUP_FILE"
        else
            echo "No backup file found. Attempting manual cleanup..."
            # Remove the hosts block from Corefile
            kubectl get configmap coredns -n "$COREDNS_NS" -o json | \
            python3 -c "
import json, sys, re
cm = json.load(sys.stdin)
corefile = cm['data']['Corefile']
# Remove the injected hosts block
# Pattern: '    hosts {\n        10.0.255.254 ...\n        fallthrough\n    }\n'
corefile = re.sub(r'\s*hosts\s*\{[^}]*10\.0\.255\.254[^}]*\}\s*\n?', '\n', corefile)
cm['data']['Corefile'] = corefile
json.dump(cm, sys.stdout)
" | kubectl apply -f -
        fi

        echo "Restarting CoreDNS..."
        kubectl rollout restart deployment coredns -n "$COREDNS_NS"
        kubectl rollout status deployment coredns -n "$COREDNS_NS" --timeout=90s

        echo "Waiting 30s for DNS to recover..."
        sleep 30

        echo "DNS verification:"
        REDIS_REAL_IP=$(kubectl get svc redis-cart -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}')
        echo "  Expected: $REDIS_REAL_IP"
        kubectl exec -n "$NAMESPACE" deploy/cartservice -- \
            sh -c "getent hosts redis-cart.${NAMESPACE}.svc.cluster.local 2>/dev/null" \
            2>/dev/null || echo "  (checking...)"

        echo ""
        echo "Restarting affected services to clear cached connections..."
        kubectl rollout restart deployment cartservice -n "$NAMESPACE"
        kubectl rollout restart deployment checkoutservice -n "$NAMESPACE"
        kubectl rollout status deployment cartservice -n "$NAMESPACE" --timeout=120s
        kubectl rollout status deployment checkoutservice -n "$NAMESPACE" --timeout=120s

        echo ""
        echo "Pod status:"
        kubectl get pods -n "$NAMESPACE" --no-headers | head -15

        # Cleanup backup
        rm -f "$BACKUP_FILE"
        echo ""
        echo "Recovery complete."
        ;;

    *)
        echo "Usage: $0 [inject|verify|recover]"
        exit 1
        ;;
esac
