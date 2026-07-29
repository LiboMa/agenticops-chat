#!/usr/bin/env bash
# Classic L2+ Kubernetes faults for the agenticops-chaos-lab cluster.
#
# These workloads are deliberately given PRODUCTION-LIKE names and NO
# chaos/experiment labels, so the agent cannot trivially recognise them as
# fault injections and must genuinely diagnose + repair them (as it would a
# real incident) rather than "stop the experiment". They live in the chaos-lab
# namespace for isolation and are trivially reversible by name.
#
# App set (a fictional "storefront" platform):
#   payment-svc          — OOMKilled loop (`tail /dev/zero` vs a 24Mi limit)
#   checkout-api         — liveness probe misconfig (wrong port) -> restart loop
#   session-store        — missing Secret ref -> CreateContainerConfigError
#   inventory-db         — PVC pending (unbindable StorageClass)
#   notification-worker  — PDB deadlock (single replica, minAvailable=1)
#
# Usage:
#   bash l2-faults.sh inject <oom|liveness|secret|pvc|pdb|all>
#   bash l2-faults.sh restore <oom|liveness|secret|pvc|pdb|all>
set -euo pipefail
NS="chaos-lab"
ACTION="${1:-}"
NAME="${2:-}"
PART_OF="storefront"   # neutral, production-sounding grouping label (NOT 'chaos')

inject_oom() {
  # payment-svc: undersized memory limit + a workload that grows memory ->
  # OOMKilled -> CrashLoopBackOff -> PodRestarts-High.
  kubectl apply -n "$NS" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-svc
  namespace: $NS
  labels: { app: payment-svc, app.kubernetes.io/part-of: $PART_OF }
spec:
  replicas: 1
  selector: { matchLabels: { app: payment-svc } }
  template:
    metadata: { labels: { app: payment-svc, app.kubernetes.io/part-of: $PART_OF } }
    spec:
      nodeSelector: { role: chaos-lab }
      containers:
        - name: payment-svc
          image: busybox:1.36
          command: ["sh","-c","echo starting payment-svc; tail /dev/zero"]
          resources:
            requests: { memory: 16Mi, cpu: 10m }
            limits: { memory: 24Mi, cpu: 100m }
EOF
  echo "[oom] payment-svc deployed (24Mi limit) -> OOMKilled/CrashLoopBackOff expected"
}

inject_liveness() {
  # checkout-api: liveness probe points at a port nothing listens on ->
  # kubelet keeps killing an otherwise-healthy container -> restart loop.
  kubectl apply -n "$NS" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout-api
  namespace: $NS
  labels: { app: checkout-api, app.kubernetes.io/part-of: $PART_OF }
spec:
  replicas: 2
  selector: { matchLabels: { app: checkout-api } }
  template:
    metadata: { labels: { app: checkout-api, app.kubernetes.io/part-of: $PART_OF } }
    spec:
      nodeSelector: { role: chaos-lab }
      containers:
        - name: checkout-api
          image: nginx:1.25-alpine
          ports: [ { containerPort: 80 } ]
          livenessProbe:
            httpGet: { path: /, port: 8081 }   # app listens on 80, not 8081
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 2
          resources:
            requests: { memory: 32Mi, cpu: 10m }
            limits: { memory: 128Mi, cpu: 200m }
EOF
  echo "[liveness] checkout-api deployed (liveness on wrong port 8081) -> restart loop expected"
}

inject_secret() {
  # session-store: references a Secret that does not exist ->
  # CreateContainerConfigError; pod never starts.
  kubectl apply -n "$NS" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: session-store
  namespace: $NS
  labels: { app: session-store, app.kubernetes.io/part-of: $PART_OF }
spec:
  replicas: 1
  selector: { matchLabels: { app: session-store } }
  template:
    metadata: { labels: { app: session-store, app.kubernetes.io/part-of: $PART_OF } }
    spec:
      nodeSelector: { role: chaos-lab }
      containers:
        - name: redis
          image: redis:7-alpine
          envFrom:
            - secretRef: { name: session-store-credentials }   # not created
          resources:
            requests: { memory: 32Mi, cpu: 10m }
            limits: { memory: 128Mi, cpu: 200m }
EOF
  echo "[secret] session-store deployed (envFrom missing secret) -> CreateContainerConfigError expected"
}

inject_pvc() {
  # inventory-db: PVC with a StorageClass that does not exist -> PVC Pending -> pod Pending.
  kubectl apply -n "$NS" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: inventory-db-data
  namespace: $NS
  labels: { app: inventory-db, app.kubernetes.io/part-of: $PART_OF }
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: fast-ssd-retain   # no such StorageClass on this cluster
  resources: { requests: { storage: 1Gi } }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: inventory-db
  namespace: $NS
  labels: { app: inventory-db, app.kubernetes.io/part-of: $PART_OF }
spec:
  replicas: 1
  selector: { matchLabels: { app: inventory-db } }
  template:
    metadata: { labels: { app: inventory-db, app.kubernetes.io/part-of: $PART_OF } }
    spec:
      nodeSelector: { role: chaos-lab }
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: inventory-db-data }
      containers:
        - name: postgres
          image: postgres:16-alpine
          env: [ { name: POSTGRES_PASSWORD, value: devpw } ]
          volumeMounts: [ { name: data, mountPath: /var/lib/postgresql/data } ]
          resources:
            requests: { memory: 64Mi, cpu: 20m }
            limits: { memory: 256Mi, cpu: 300m }
EOF
  echo "[pvc] inventory-db deployed + PVC (StorageClass fast-ssd-retain) -> PVC/pod Pending expected"
}

inject_pdb() {
  # notification-worker: single replica guarded by a PDB requiring
  # minAvailable=1 -> any voluntary eviction (drain/rollout) is blocked.
  kubectl apply -n "$NS" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: notification-worker
  namespace: $NS
  labels: { app: notification-worker, app.kubernetes.io/part-of: $PART_OF }
spec:
  replicas: 1
  selector: { matchLabels: { app: notification-worker } }
  template:
    metadata: { labels: { app: notification-worker, app.kubernetes.io/part-of: $PART_OF } }
    spec:
      nodeSelector: { role: chaos-lab }
      containers:
        - name: worker
          image: nginx:1.25-alpine
          resources:
            requests: { memory: 32Mi, cpu: 10m }
            limits: { memory: 128Mi, cpu: 200m }
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: notification-worker-pdb
  namespace: $NS
  labels: { app: notification-worker, app.kubernetes.io/part-of: $PART_OF }
spec:
  minAvailable: 1                 # with replicas=1 this blocks ALL evictions
  selector: { matchLabels: { app: notification-worker } }
EOF
  echo "[pdb] notification-worker deployed (replicas=1) + PDB minAvailable=1 -> eviction/drain deadlock"
}

restore_one() {
  case "$1" in
    oom)      kubectl delete deploy payment-svc -n "$NS" --ignore-not-found ;;
    liveness) kubectl delete deploy checkout-api -n "$NS" --ignore-not-found ;;
    secret)   kubectl delete deploy session-store -n "$NS" --ignore-not-found; kubectl delete secret session-store-credentials -n "$NS" --ignore-not-found 2>/dev/null || true ;;
    pvc)      kubectl delete deploy inventory-db -n "$NS" --ignore-not-found; kubectl delete pvc inventory-db-data -n "$NS" --ignore-not-found ;;
    pdb)      kubectl delete deploy notification-worker -n "$NS" --ignore-not-found; kubectl delete pdb notification-worker-pdb -n "$NS" --ignore-not-found ;;
    *) echo "unknown fault: $1"; exit 1 ;;
  esac
}

case "$ACTION" in
  inject)
    case "$NAME" in
      oom) inject_oom ;; liveness) inject_liveness ;; secret) inject_secret ;;
      pvc) inject_pvc ;; pdb) inject_pdb ;;
      all) inject_oom; inject_liveness; inject_secret; inject_pvc; inject_pdb ;;
      *) echo "Usage: bash l2-faults.sh inject <oom|liveness|secret|pvc|pdb|all>"; exit 1 ;;
    esac ;;
  restore)
    if [ "$NAME" = "all" ]; then for n in oom liveness secret pvc pdb; do restore_one "$n"; done
    else restore_one "$NAME"; fi
    echo "restore done" ;;
  *) echo "Usage: bash l2-faults.sh <inject|restore> <oom|liveness|secret|pvc|pdb|all>"; exit 1 ;;
esac
