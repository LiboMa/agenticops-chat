# EKS Chaos E2E — In-Cluster AgenticOps + Four-Phase Verification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy AgenticOps internal-only on the existing `agenticops-chaos-lab` EKS cluster and build a remote-runnable E2E harness that proves the 感知→分析→解决→记录 loop against injected faults.

**Architecture:** The app runs as a `ClusterIP` Deployment in an `agenticops` namespace (no public ingress). It perceives AWS via IRSA (readonly + Bedrock) and fixes the cluster via an in-cluster ServiceAccount kubeconfig (scoped RBAC). A pytest harness on a remote server tunnels in with `kubectl port-forward`, injects chaos with the existing scripts, and asserts each phase via the REST API (assert mode) or captures chat+report evidence (evidence mode).

**Tech Stack:** EKS (eksctl), Docker/ECR, Kubernetes manifests, IRSA, Python 3.12 + pytest + requests/httpx, bash.

## Global Constraints

- **NEVER expose the app to the public internet** — `Service` is `ClusterIP` only; no LoadBalancer, no NodePort, no ALB, no CloudFront. Sole ingress is `kubectl port-forward` from the remote server.
- **凭证铁律:** single account (monitor == target). Register with `credential_source_type: "environment"` (the only legal default-chain declaration); resolved + validated via `GetCallerIdentity`. No ambient fallback, no cross-account AssumeRole.
- **Least-privilege RBAC:** no `cluster-admin`. Read-all cluster-wide + node patch; mutating verbs namespaced to `chaos-lab`; coredns patch namespaced to `kube-system`.
- **Reuse, don't rebuild:** existing `docker/` image unmodified, existing `infra/eks-chaos-lab/chaos/*.sh` scripts, existing cluster `agenticops-chaos-lab` (us-east-1).
- **No changes to `src/agenticops/`** are required; if a gap surfaces, stop and flag it.
- **Cluster:** `agenticops-chaos-lab`, region `us-east-1`, target namespace `chaos-lab`, app namespace `agenticops`.
- **git:** commit per task; **`git push --no-verify`** only, and only when the user asks. Do not push during implementation.
- **Offline CI tests** live under repo `tests/`; **live E2E** lives under `infra/eks-chaos-lab/e2e/` and is not part of offline CI.
- Every shell script starts `#!/usr/bin/env bash` + `set -euo pipefail`; every manifest passes `kubectl apply --dry-run=client`.

---

## File Structure

```
infra/eks-chaos-lab/
├── iam/
│   └── agenticops-irsa-policy.json     # NEW: readonly + bedrock:InvokeModel*
├── agenticops/                          # NEW: in-cluster app deployment
│   ├── namespace.yaml
│   ├── rbac.yaml                        # ClusterRole + 2 Roles + bindings
│   ├── serviceaccount.yaml              # IRSA-annotated (ARN via kustomize-free sed in deploy-app.sh)
│   ├── configmap.yaml                   # AIOPS_* non-secret settings
│   ├── secret.example.yaml              # template; real Secret created by deploy-app.sh (gitignored)
│   ├── deployment.yaml                  # in-cluster kubeconfig init + uvicorn
│   ├── service.yaml                     # ClusterIP :8000
│   └── deploy-app.sh                    # build→ECR→IRSA SA→apply→wait ready
└── e2e/                                 # NEW: the harness
    ├── scenarios.yaml                   # declarative scenario registry
    ├── client.py                        # AgenticOpsClient: login→Bearer, pollers
    ├── conftest.py                      # fixtures: client, scenario loader, restore teardown
    ├── test_e2e_four_phases.py          # assert-mode scenarios
    ├── test_e2e_evidence.py             # evidence-mode scenarios
    ├── run-e2e.sh                       # port-forward → pytest → collect artifacts
    ├── results/.gitkeep                 # (results/* gitignored)
    └── README.md

tests/
└── test_chaos_e2e_client.py             # NEW: offline unit tests for client.py pollers

infra/eks-chaos-lab/e2e/scenarios/       # NEW: ported scenario scripts (coredns, service-deleted)
├── coredns-down.sh
└── service-deleted.sh
```

---

## Task 1: IRSA IAM policy (perceive + Bedrock)

**Files:**
- Create: `infra/eks-chaos-lab/iam/agenticops-irsa-policy.json`

**Interfaces:**
- Consumes: nothing.
- Produces: an IAM policy JSON document consumed by `deploy-app.sh` (Task 8) via `eksctl create iamserviceaccount --attach-policy-arn`/inline.

- [ ] **Step 1: Create the policy file**

The base is the existing `infra/eks-chaos-lab/iam/readonly-policy.json` (EC2/EKS/CloudWatch/Logs/CloudTrail/ELB read) plus Bedrock invoke. Write:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "EC2ReadOnly", "Effect": "Allow", "Action": ["ec2:Describe*", "ec2:Get*"], "Resource": "*" },
    { "Sid": "EKSReadOnly", "Effect": "Allow", "Action": ["eks:Describe*", "eks:List*"], "Resource": "*" },
    { "Sid": "CloudWatchReadOnly", "Effect": "Allow", "Action": ["cloudwatch:Describe*", "cloudwatch:Get*", "cloudwatch:List*"], "Resource": "*" },
    { "Sid": "LogsReadOnly", "Effect": "Allow", "Action": ["logs:DescribeLogGroups", "logs:DescribeLogStreams", "logs:GetLogEvents", "logs:FilterLogEvents", "logs:StartQuery", "logs:GetQueryResults", "logs:StopQuery"], "Resource": "*" },
    { "Sid": "CloudTrailReadOnly", "Effect": "Allow", "Action": ["cloudtrail:LookupEvents", "cloudtrail:DescribeTrails", "cloudtrail:GetTrailStatus", "cloudtrail:GetEventSelectors"], "Resource": "*" },
    { "Sid": "ELBReadOnly", "Effect": "Allow", "Action": ["elasticloadbalancing:Describe*"], "Resource": "*" },
    { "Sid": "BedrockInvoke", "Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*" }
  ]
}
```

- [ ] **Step 2: Validate JSON**

Run: `python3 -c "import json; json.load(open('infra/eks-chaos-lab/iam/agenticops-irsa-policy.json')); print('valid')"`
Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add infra/eks-chaos-lab/iam/agenticops-irsa-policy.json
git commit -m "feat(chaos-e2e): IRSA policy — readonly + bedrock:InvokeModel"
```

---

## Task 2: App namespace + ServiceAccount manifests

**Files:**
- Create: `infra/eks-chaos-lab/agenticops/namespace.yaml`
- Create: `infra/eks-chaos-lab/agenticops/serviceaccount.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces: namespace `agenticops`, ServiceAccount `agenticops` in it. The SA carries annotation `eks.amazonaws.com/role-arn: __IRSA_ROLE_ARN__` (placeholder replaced by `deploy-app.sh` at apply time via `sed`).

- [ ] **Step 1: Write namespace.yaml**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: agenticops
  labels:
    app.kubernetes.io/part-of: agenticops
    purpose: chaos-e2e-monitor
```

- [ ] **Step 2: Write serviceaccount.yaml**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: agenticops
  namespace: agenticops
  annotations:
    # Replaced by deploy-app.sh with the IRSA role ARN created by eksctl.
    eks.amazonaws.com/role-arn: __IRSA_ROLE_ARN__
```

- [ ] **Step 3: Dry-run validate**

Run: `kubectl apply --dry-run=client -f infra/eks-chaos-lab/agenticops/namespace.yaml -f infra/eks-chaos-lab/agenticops/serviceaccount.yaml`
Expected: `namespace/agenticops created (dry run)` and `serviceaccount/agenticops created (dry run)` (or `configured (dry run)`). No schema errors.

> Note: dry-run may need the cluster reachable. If offline, instead run `python3 -c "import yaml,sys; list(yaml.safe_load_all(open('infra/eks-chaos-lab/agenticops/namespace.yaml'))); print('yaml ok')"` for each file.

- [ ] **Step 4: Commit**

```bash
git add infra/eks-chaos-lab/agenticops/namespace.yaml infra/eks-chaos-lab/agenticops/serviceaccount.yaml
git commit -m "feat(chaos-e2e): app namespace + IRSA-annotated ServiceAccount"
```

---

## Task 3: Scoped RBAC manifests

**Files:**
- Create: `infra/eks-chaos-lab/agenticops/rbac.yaml`

**Interfaces:**
- Consumes: ServiceAccount `agenticops/agenticops` (Task 2).
- Produces: `ClusterRole agenticops-observe` + `ClusterRoleBinding`; `Role agenticops-remediate` (ns `chaos-lab`) + binding; `Role agenticops-dns-remediate` (ns `kube-system`) + binding. These grant the exact verbs the fix path needs — later tasks assume the SA can scale/patch deployments in `chaos-lab`, patch nodes, delete pods/netpols, and scale coredns.

- [ ] **Step 1: Write rbac.yaml**

```yaml
# Cluster-wide READ + node uncordon (patch nodes) + pod eviction (drain recovery).
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: agenticops-observe
rules:
  - apiGroups: [""]
    resources: [pods, nodes, services, endpoints, events, namespaces, configmaps, persistentvolumeclaims, persistentvolumes, replicationcontrollers]
    verbs: [get, list, watch]
  - apiGroups: ["apps"]
    resources: [deployments, replicasets, statefulsets, daemonsets]
    verbs: [get, list, watch]
  - apiGroups: ["networking.k8s.io"]
    resources: [networkpolicies, ingresses]
    verbs: [get, list, watch]
  - apiGroups: ["autoscaling"]
    resources: [horizontalpodautoscalers]
    verbs: [get, list, watch]
  - apiGroups: ["metrics.k8s.io"]
    resources: [pods, nodes]
    verbs: [get, list]
  - apiGroups: [""]
    resources: [nodes]
    verbs: [patch]                 # uncordon
  - apiGroups: [""]
    resources: [pods/eviction]
    verbs: [create]                # drain recovery
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: agenticops-observe
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: agenticops-observe
subjects:
  - kind: ServiceAccount
    name: agenticops
    namespace: agenticops
---
# Mutating verbs — SCOPED to the chaos-lab target namespace only.
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: agenticops-remediate
  namespace: chaos-lab
rules:
  - apiGroups: ["apps"]
    resources: [deployments, deployments/scale, replicasets]
    verbs: [get, list, watch, patch, update]
  - apiGroups: [""]
    resources: [pods]
    verbs: [get, list, watch, delete]
  - apiGroups: [""]
    resources: [configmaps, services]
    verbs: [get, list, watch, create, update, patch]
  - apiGroups: ["networking.k8s.io"]
    resources: [networkpolicies]
    verbs: [get, list, watch, delete]
  - apiGroups: ["batch"]
    resources: [jobs]
    verbs: [get, list, watch, delete]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: agenticops-remediate
  namespace: chaos-lab
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: agenticops-remediate
subjects:
  - kind: ServiceAccount
    name: agenticops
    namespace: agenticops
---
# CoreDNS scale-back — SCOPED to kube-system, deployments only, patch/scale only.
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: agenticops-dns-remediate
  namespace: kube-system
rules:
  - apiGroups: ["apps"]
    resources: [deployments, deployments/scale]
    verbs: [get, list, watch, patch, update]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: agenticops-dns-remediate
  namespace: kube-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: agenticops-dns-remediate
subjects:
  - kind: ServiceAccount
    name: agenticops
    namespace: agenticops
```

- [ ] **Step 2: Validate YAML parses (offline-safe)**

Run: `python3 -c "import yaml; docs=list(yaml.safe_load_all(open('infra/eks-chaos-lab/agenticops/rbac.yaml'))); print(f'{len(docs)} docs'); assert not any('cluster-admin' in str(d) for d in docs), 'cluster-admin forbidden'; print('no cluster-admin ok')"`
Expected: `6 docs` then `no cluster-admin ok`

- [ ] **Step 3: Commit**

```bash
git add infra/eks-chaos-lab/agenticops/rbac.yaml
git commit -m "feat(chaos-e2e): scoped RBAC — observe cluster-wide, remediate in chaos-lab/kube-system"
```

---

## Task 4: App ConfigMap + Secret template

**Files:**
- Create: `infra/eks-chaos-lab/agenticops/configmap.yaml`
- Create: `infra/eks-chaos-lab/agenticops/secret.example.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces: ConfigMap `agenticops-config` (non-secret `AIOPS_*` env) and a Secret template. `deployment.yaml` (Task 5) references ConfigMap `agenticops-config` and Secret `agenticops-secret` via `envFrom`.

- [ ] **Step 1: Write configmap.yaml**

Values chosen so the four-phase auto-chain runs unattended (auto-fix on, auto-approve L0/L1 on, HITL off), Bedrock in us-east-1, DB on an emptyDir SQLite path.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agenticops-config
  namespace: agenticops
data:
  AIOPS_BEDROCK_REGION: "us-east-1"
  AIOPS_AUTO_RCA_ENABLED: "true"
  AIOPS_AUTO_FIX_ENABLED: "true"
  AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1: "true"
  AIOPS_EXECUTOR_HITL_ENABLED: "false"
  AIOPS_NOTIFICATIONS_ENABLED: "false"
  AIOPS_API_AUTH_ENABLED: "true"
  AIOPS_EKS_CLUSTER_NAME: "agenticops-chaos-lab"
  AIOPS_DATABASE_URL: "sqlite:////data/agenticops.db"
  KUBECONFIG: "/var/run/agenticops/kubeconfig"
```

- [ ] **Step 2: Write secret.example.yaml**

```yaml
# TEMPLATE ONLY — do not `kubectl apply` this. deploy-app.sh creates the real
# Secret named `agenticops-secret` from --from-literal (gitignored value).
apiVersion: v1
kind: Secret
metadata:
  name: agenticops-secret
  namespace: agenticops
type: Opaque
stringData:
  AIOPS_ADMIN_PASSWORD: "CHANGE_ME"
```

- [ ] **Step 3: Validate YAML**

Run: `python3 -c "import yaml; [list(yaml.safe_load_all(open(f))) for f in ['infra/eks-chaos-lab/agenticops/configmap.yaml','infra/eks-chaos-lab/agenticops/secret.example.yaml']]; print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 4: Commit**

```bash
git add infra/eks-chaos-lab/agenticops/configmap.yaml infra/eks-chaos-lab/agenticops/secret.example.yaml
git commit -m "feat(chaos-e2e): app ConfigMap (auto-fix chain on) + Secret template"
```

---

## Task 5: App Deployment + Service (ClusterIP, in-cluster kubeconfig)

**Files:**
- Create: `infra/eks-chaos-lab/agenticops/deployment.yaml`
- Create: `infra/eks-chaos-lab/agenticops/service.yaml`

**Interfaces:**
- Consumes: SA `agenticops` (Task 2), RBAC (Task 3), ConfigMap `agenticops-config` + Secret `agenticops-secret` (Task 4). Image ref `__IMAGE__` (replaced by `deploy-app.sh`).
- Produces: Deployment `agenticops` and Service `agenticops` (ClusterIP :8000, selector `app=agenticops`) in ns `agenticops`. The pod writes an in-cluster kubeconfig at `$KUBECONFIG` before starting uvicorn, so `run_kubectl` uses the SA token.

- [ ] **Step 1: Write deployment.yaml**

An init step writes a kubeconfig from the projected SA token + CA into an emptyDir shared with the app container. The existing `docker/` image entrypoint runs uvicorn; we override command to first write the kubeconfig.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agenticops
  namespace: agenticops
  labels: { app: agenticops }
spec:
  replicas: 1
  selector:
    matchLabels: { app: agenticops }
  template:
    metadata:
      labels: { app: agenticops }
    spec:
      serviceAccountName: agenticops
      volumes:
        - name: kubeconfig
          emptyDir: {}
        - name: data
          emptyDir: {}
      initContainers:
        - name: write-kubeconfig
          image: __IMAGE__
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -eu
              TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
              CA=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
              cat > /var/run/agenticops/kubeconfig <<EOF
              apiVersion: v1
              kind: Config
              clusters:
              - name: in-cluster
                cluster:
                  server: https://kubernetes.default.svc
                  certificate-authority: ${CA}
              contexts:
              - name: in-cluster
                context:
                  cluster: in-cluster
                  user: agenticops-sa
                  namespace: chaos-lab
              current-context: in-cluster
              users:
              - name: agenticops-sa
                user:
                  token: ${TOKEN}
              EOF
              echo "kubeconfig written"
          volumeMounts:
            - { name: kubeconfig, mountPath: /var/run/agenticops }
      containers:
        - name: agenticops
          image: __IMAGE__
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef: { name: agenticops-config }
            - secretRef: { name: agenticops-secret }
          volumeMounts:
            - { name: kubeconfig, mountPath: /var/run/agenticops }
            - { name: data, mountPath: /data }
          readinessProbe:
            httpGet: { path: /api/health, port: 8000 }
            initialDelaySeconds: 15
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /api/health, port: 8000 }
            initialDelaySeconds: 40
            periodSeconds: 20
          resources:
            requests: { cpu: "500m", memory: "1Gi" }
            limits: { cpu: "2", memory: "3Gi" }
```

> The token in the kubeconfig is the SA's projected token (default expiry). If a long run outlives it, `deploy-app.sh` supports `kubectl rollout restart`. YAGNI: no token-refresh sidecar unless a run actually exceeds token TTL.

- [ ] **Step 2: Write service.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: agenticops
  namespace: agenticops
  labels: { app: agenticops }
spec:
  type: ClusterIP          # HARD RULE: never LoadBalancer/NodePort — app stays private
  selector: { app: agenticops }
  ports:
    - name: http
      port: 8000
      targetPort: 8000
```

- [ ] **Step 3: Validate YAML + assert no public service type**

Run:
```bash
python3 -c "import yaml; d=list(yaml.safe_load_all(open('infra/eks-chaos-lab/agenticops/service.yaml'))); assert d[0]['spec']['type']=='ClusterIP', 'must be ClusterIP'; print('ClusterIP ok')"
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/eks-chaos-lab/agenticops/deployment.yaml'))); print('deployment yaml ok')"
```
Expected: `ClusterIP ok` then `deployment yaml ok`

- [ ] **Step 4: Commit**

```bash
git add infra/eks-chaos-lab/agenticops/deployment.yaml infra/eks-chaos-lab/agenticops/service.yaml
git commit -m "feat(chaos-e2e): app Deployment (in-cluster kubeconfig) + ClusterIP Service"
```

---

## Task 6: `deploy-app.sh` — build → ECR → IRSA SA → apply → wait

**Files:**
- Create: `infra/eks-chaos-lab/agenticops/deploy-app.sh`

**Interfaces:**
- Consumes: all manifests (Tasks 2–5), IRSA policy (Task 1), `docker/build.sh`.
- Produces: a running, ready `agenticops` Deployment. Prints the port-forward command. `run-e2e.sh` (Task 12) assumes `svc/agenticops -n agenticops` exists and `/api/health` returns ok.

- [ ] **Step 1: Write deploy-app.sh**

```bash
#!/usr/bin/env bash
# Deploy AgenticOps into the chaos-lab EKS cluster (internal-only).
# Steps: ensure ECR repo → build+push image → create IRSA SA → apply manifests → wait ready.
# Usage: bash deploy-app.sh [--admin-password PW]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CLUSTER="agenticops-chaos-lab"
REGION="us-east-1"
NS="agenticops"
ECR_REPO_NAME="agenticops"
IAM_POLICY_FILE="${SCRIPT_DIR}/../iam/agenticops-irsa-policy.json"
ADMIN_PW="aiops2026"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --admin-password) ADMIN_PW="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

# HARD RULE guard: refuse if any manifest declares a public Service type.
if grep -rEn "type:\s*(LoadBalancer|NodePort)" "${SCRIPT_DIR}"/*.yaml; then
  echo "ERROR: public Service type found — app must stay ClusterIP. Aborting."
  exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
ECR_URL="${REGISTRY}/${ECR_REPO_NAME}"

echo "[1/6] Ensure ECR repo ${ECR_REPO_NAME}"
aws ecr describe-repositories --repository-names "${ECR_REPO_NAME}" --region "${REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${ECR_REPO_NAME}" --region "${REGION}" >/dev/null

echo "[2/6] Build + push image"
AWS_REGION="${REGION}" bash "${REPO_ROOT}/docker/build.sh" push "${ECR_URL}"
IMAGE_TAG=$(cd "${REPO_ROOT}" && git rev-parse --short HEAD)
IMAGE="${ECR_URL}:${IMAGE_TAG}"

echo "[3/6] Create IRSA ServiceAccount (idempotent)"
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/AgenticOpsIRSAPolicy"
aws iam get-policy --policy-arn "${POLICY_ARN}" >/dev/null 2>&1 \
  || aws iam create-policy --policy-name AgenticOpsIRSAPolicy \
       --policy-document "file://${IAM_POLICY_FILE}" >/dev/null
kubectl create namespace "${NS}" --dry-run=client -o yaml | kubectl apply -f -
eksctl create iamserviceaccount \
  --cluster "${CLUSTER}" --region "${REGION}" \
  --namespace "${NS}" --name agenticops \
  --attach-policy-arn "${POLICY_ARN}" \
  --approve --override-existing-serviceaccounts
IRSA_ROLE_ARN=$(aws iam list-roles \
  --query "Roles[?contains(RoleName, 'agenticops') && contains(RoleName, 'chaos-lab')].Arn | [0]" \
  --output text 2>/dev/null || echo "")
# Fallback: read the annotation eksctl set on the SA.
if [[ -z "${IRSA_ROLE_ARN}" || "${IRSA_ROLE_ARN}" == "None" ]]; then
  IRSA_ROLE_ARN=$(kubectl get sa agenticops -n "${NS}" -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}')
fi
echo "  IRSA role: ${IRSA_ROLE_ARN}"

echo "[4/6] Create app Secret"
kubectl create secret generic agenticops-secret -n "${NS}" \
  --from-literal=AIOPS_ADMIN_PASSWORD="${ADMIN_PW}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[5/6] Apply manifests (SA annotation + image substituted)"
sed "s#__IRSA_ROLE_ARN__#${IRSA_ROLE_ARN}#g" "${SCRIPT_DIR}/serviceaccount.yaml" | kubectl apply -f -
kubectl apply -f "${SCRIPT_DIR}/rbac.yaml"
kubectl apply -f "${SCRIPT_DIR}/configmap.yaml"
sed "s#__IMAGE__#${IMAGE}#g" "${SCRIPT_DIR}/deployment.yaml" | kubectl apply -f -
kubectl apply -f "${SCRIPT_DIR}/service.yaml"

echo "[6/6] Wait for rollout"
kubectl rollout status deployment/agenticops -n "${NS}" --timeout=300s

cat <<EOF

Deployed. App is ClusterIP-only (no public ingress).
Reach it from this machine:
  kubectl port-forward svc/agenticops -n ${NS} 8000:8000
Then: curl -s localhost:8000/api/health
EOF
```

- [ ] **Step 2: Syntax check**

Run: `bash -n infra/eks-chaos-lab/agenticops/deploy-app.sh && echo "syntax ok"`
Expected: `syntax ok`

- [ ] **Step 3: Assert the public-type guard grep is present**

Run: `grep -q 'LoadBalancer|NodePort' infra/eks-chaos-lab/agenticops/deploy-app.sh && echo "guard present"`
Expected: `guard present`

- [ ] **Step 4: Commit**

```bash
git add infra/eks-chaos-lab/agenticops/deploy-app.sh
git commit -m "feat(chaos-e2e): deploy-app.sh — build/ECR/IRSA/apply, ClusterIP guard"
```

---

## Task 7: `client.py` — API client + pollers (with offline unit tests)

**Files:**
- Create: `infra/eks-chaos-lab/e2e/client.py`
- Create: `tests/test_chaos_e2e_client.py`

**Interfaces:**
- Consumes: the AgenticOps REST API (verified endpoints): `POST /api/auth/login` → `{token,...}`; `GET /api/health-issues?limit=`; `GET /api/health-issues/{id}`; `GET /api/health-issues/{id}/rca` → list; `GET /api/fix-plans?health_issue_id=`; `GET /api/health-issues/{id}/timeline`; `GET /api/trace/{trace_id}`; `POST /api/webhooks/alert/cloudwatch`; `POST /api/accounts`; `POST /api/chat/sessions`; `POST /api/chat/sessions/{id}/messages`.
- Produces: class `AgenticOpsClient` with methods used by all test tasks:
  - `login(email: str, password: str) -> None` (stores Bearer token)
  - `get(path: str) -> Any`, `post(path: str, json: dict) -> Any` (auth headers auto-applied)
  - `find_recent_issue(title_pattern: str, max_age_min: int = 15) -> Optional[int]`
  - `wait_for_issue(title_pattern: str, timeout_s: int, poll_s: int = 5) -> int`
  - `wait_for_status(issue_id: int, targets: set[str], timeout_s: int, poll_s: int = 5) -> str`
  - `has_rca(issue_id: int) -> bool`
  - `get_fix_plan(issue_id: int) -> Optional[dict]`
  - `get_timeline(issue_id: int) -> list[dict]`
  - `ensure_account(name: str, account_id: str, regions: list[str]) -> None` (idempotent, `environment` source)
  - `send_cloudwatch_alert(payload: dict) -> Any`
  - Custom exception `PhaseTimeout(phase: str, detail: str)` so failures name the phase.

- [ ] **Step 1: Write the failing unit test**

`tests/test_chaos_e2e_client.py` — pure offline, mocks HTTP via a fake transport. Tests the two trickiest pollers.

```python
import sys, types, importlib.util, pathlib
import pytest

# Load client.py from infra/ (not a package) by path.
_CLIENT = pathlib.Path(__file__).resolve().parents[1] / "infra/eks-chaos-lab/e2e/client.py"
spec = importlib.util.spec_from_file_location("chaos_e2e_client", _CLIENT)
client_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_mod)
AgenticOpsClient = client_mod.AgenticOpsClient
PhaseTimeout = client_mod.PhaseTimeout


class _FakeResp:
    def __init__(self, status, payload): self.status_code, self._p = status, payload
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


def _mk(monkeypatch, sequence):
    """monkeypatch client.get to return successive payloads from `sequence`."""
    calls = {"i": 0}
    def fake_get(path):
        p = sequence[min(calls["i"], len(sequence) - 1)]
        calls["i"] += 1
        return p
    return calls, fake_get


def test_find_recent_issue_matches_pattern_and_skips_resolved(monkeypatch):
    c = AgenticOpsClient("http://x")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    payload = [
        {"id": 1, "title": "old resolved", "description": "", "status": "resolved", "detected_at": now},
        {"id": 2, "title": "frontend replicas scaled to zero", "description": "", "status": "open", "detected_at": now},
    ]
    monkeypatch.setattr(c, "get", lambda path: payload)
    assert c.find_recent_issue(r"replicas|scaled") == 2


def test_wait_for_status_raises_phasetimeout_named(monkeypatch):
    c = AgenticOpsClient("http://x")
    monkeypatch.setattr(c, "get", lambda path: {"status": "investigating"})
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(client_mod.time, "monotonic", _fake_clock([0, 1, 2, 3, 999]))
    with pytest.raises(PhaseTimeout) as ei:
        c.wait_for_status(5, {"resolved"}, timeout_s=2)
    assert "resolve" in str(ei.value).lower() or ei.value.phase == "resolve"


def _fake_clock(values):
    it = iter(values)
    last = [0]
    def clock():
        try: last[0] = next(it)
        except StopIteration: pass
        return last[0]
    return clock
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_chaos_e2e_client.py -v`
Expected: FAIL — `client.py` does not exist yet (import error).

- [ ] **Step 3: Write client.py**

```python
"""AgenticOps E2E client — login, REST helpers, and phase pollers.

Runs from a remote server against a port-forwarded ClusterIP app.
Depends only on `requests` (stdlib + requests) so it needs no repo imports.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests


class PhaseTimeout(Exception):
    """Raised when a phase (perceive/analyze/resolve/record) does not complete in time."""
    def __init__(self, phase: str, detail: str):
        self.phase = phase
        super().__init__(f"[{phase}] {detail}")


class AgenticOpsClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token: Optional[str] = None

    # ---- auth ----
    def login(self, email: str, password: str) -> None:
        r = requests.post(f"{self.base_url}/api/auth/login",
                          json={"email": email, "password": password}, timeout=self.timeout)
        r.raise_for_status()
        self._token = r.json()["token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def get(self, path: str) -> Any:
        r = requests.get(f"{self.base_url}{path}", headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json: Optional[dict] = None) -> Any:
        r = requests.post(f"{self.base_url}{path}", headers=self._headers(),
                          json=json or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    # ---- account registration (idempotent, environment source) ----
    def ensure_account(self, name: str, account_id: str, regions: list[str]) -> None:
        existing = self.get("/api/accounts")
        if any(a.get("name") == name for a in existing):
            return
        self.post("/api/accounts", json={
            "name": name, "provider": "aws",
            "credential_source_type": "environment",
            "credentials": {"account_id": account_id},
            "regions": regions, "is_enabled": True,
        })

    # ---- perception ----
    def send_cloudwatch_alert(self, payload: dict) -> Any:
        return self.post("/api/webhooks/alert/cloudwatch", json=payload)

    def find_recent_issue(self, title_pattern: str, max_age_min: int = 15) -> Optional[int]:
        data = self.get("/api/health-issues?limit=30")
        items = data if isinstance(data, list) else data.get("items", [])
        pat = re.compile(title_pattern, re.IGNORECASE)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_min)
        for it in items:
            if it.get("status") in ("resolved", "closed"):
                continue
            det = it.get("detected_at") or it.get("created_at") or ""
            try:
                dt = datetime.fromisoformat(det.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
            text = f"{it.get('title','')} {it.get('description','')}"
            if pat.search(text):
                return int(it["id"])
        return None

    def wait_for_issue(self, title_pattern: str, timeout_s: int, poll_s: int = 5) -> int:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            found = self.find_recent_issue(title_pattern)
            if found is not None:
                return found
            time.sleep(poll_s)
        raise PhaseTimeout("perceive", f"no HealthIssue matched /{title_pattern}/ in {timeout_s}s")

    # ---- analysis ----
    def has_rca(self, issue_id: int) -> bool:
        rca = self.get(f"/api/health-issues/{issue_id}/rca")
        return bool(rca)

    # ---- resolution ----
    def get_fix_plan(self, issue_id: int) -> Optional[dict]:
        plans = self.get(f"/api/fix-plans?health_issue_id={issue_id}")
        items = plans if isinstance(plans, list) else plans.get("items", [])
        return items[0] if items else None

    def wait_for_status(self, issue_id: int, targets: set[str], timeout_s: int, poll_s: int = 5) -> str:
        deadline = time.monotonic() + timeout_s
        current = ""
        while time.monotonic() < deadline:
            current = self.get(f"/api/health-issues/{issue_id}").get("status", "")
            if current in targets:
                return current
            time.sleep(poll_s)
        raise PhaseTimeout("resolve", f"issue {issue_id} stuck at '{current}', wanted {targets}")

    # ---- record ----
    def get_timeline(self, issue_id: int) -> list[dict]:
        tl = self.get(f"/api/health-issues/{issue_id}/timeline")
        return tl if isinstance(tl, list) else tl.get("timeline", tl.get("events", []))
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `python -m pytest tests/test_chaos_e2e_client.py -v`
Expected: PASS (2 tests). If `requests` import fails offline, it is already a dependency — confirm with `python -c "import requests"`.

- [ ] **Step 5: Commit**

```bash
git add infra/eks-chaos-lab/e2e/client.py tests/test_chaos_e2e_client.py
git commit -m "feat(chaos-e2e): API client + phase pollers with offline unit tests"
```

---

## Task 8: `scenarios.yaml` — declarative registry

**Files:**
- Create: `infra/eks-chaos-lab/e2e/scenarios.yaml`

**Interfaces:**
- Consumes: existing chaos scripts under `infra/eks-chaos-lab/chaos/` and (Task 11) `infra/eks-chaos-lab/e2e/scenarios/`.
- Produces: a list of scenario dicts loaded by `conftest.py` (Task 9). Each dict has keys: `id, mode (assert|evidence), description, inject, restore, perceive{alert, title_pattern}, expect_fix{kind, ...}, timeout_perceive_s, timeout_resolve_s`. `alert` is the CloudWatch webhook payload to POST; `expect_fix.kind` ∈ {`replicas_min`, `image_not_contains`, `node_schedulable`, `no_pod_label`, `no_networkpolicy`, `coredns_min`, `service_exists`}.

- [ ] **Step 1: Write scenarios.yaml (6 assert + 2 evidence)**

```yaml
# Each scenario: inject a fault, perceive via a CloudWatch webhook, assert the
# four phases (or capture evidence), then restore. Paths are relative to the
# eks-chaos-lab directory. `alert` mirrors a genuine CloudWatch alarm transition.
- id: scale-to-zero
  mode: assert
  description: Frontend + backend scaled to 0 replicas
  inject:  "chaos/pod-kill.sh scale-zero"
  restore: "chaos/pod-kill.sh restore"
  perceive:
    title_pattern: "running pods|replicas|scaled|pods"
    alert:
      AlarmName: "EKS-agenticops-chaos-lab-RunningPods-Low"
      NewStateValue: "ALARM"
      NewStateReason: "Running pod count below threshold in chaos-lab"
      Trigger: { MetricName: "pod_number_of_running_pods", Namespace: "ContainerInsights" }
  expect_fix: { kind: replicas_min, namespace: chaos-lab, deployment: frontend, min: 1 }
  timeout_perceive_s: 120
  timeout_resolve_s: 480

- id: bad-image
  mode: assert
  description: Frontend set to a non-existent image tag (ImagePullBackOff)
  inject:  "chaos/config-break.sh bad-image"
  restore: "chaos/config-break.sh restore"
  perceive:
    title_pattern: "image|ImagePull|restart|pull"
    alert:
      AlarmName: "EKS-agenticops-chaos-lab-PodRestarts-High"
      NewStateValue: "ALARM"
      NewStateReason: "Container restart count high (ImagePullBackOff) in chaos-lab"
      Trigger: { MetricName: "pod_number_of_container_restarts", Namespace: "ContainerInsights" }
  expect_fix: { kind: image_not_contains, namespace: chaos-lab, deployment: frontend, substring: "nonexistent" }
  timeout_perceive_s: 120
  timeout_resolve_s: 480

- id: crashloop-config
  mode: assert
  description: Invalid nginx config → CrashLoopBackOff
  inject:  "chaos/config-break.sh bad-config"
  restore: "chaos/config-break.sh restore"
  perceive:
    title_pattern: "crash|config|restart|running pods"
    alert:
      AlarmName: "EKS-agenticops-chaos-lab-PodRestarts-High"
      NewStateValue: "ALARM"
      NewStateReason: "CrashLoopBackOff in chaos-lab frontend"
      Trigger: { MetricName: "pod_number_of_container_restarts", Namespace: "ContainerInsights" }
  expect_fix: { kind: replicas_min, namespace: chaos-lab, deployment: frontend, min: 1 }
  timeout_perceive_s: 120
  timeout_resolve_s: 480

- id: node-drained
  mode: assert
  description: A node cordoned + drained
  inject:  "chaos/node-drain.sh drain"
  restore: "chaos/node-drain.sh restore"
  perceive:
    title_pattern: "node|drain|cordon|schedul"
    alert:
      AlarmName: "EKS-agenticops-chaos-lab-NodeCount-Low"
      NewStateValue: "ALARM"
      NewStateReason: "Schedulable node count dropped in cluster"
      Trigger: { MetricName: "cluster_node_count", Namespace: "ContainerInsights" }
  expect_fix: { kind: node_schedulable }
  timeout_perceive_s: 120
  timeout_resolve_s: 480

- id: resource-stress
  mode: assert
  description: stress-ng pod pins node CPU/memory
  inject:  "chaos/resource-stress.sh start"
  restore: "chaos/resource-stress.sh stop"
  perceive:
    title_pattern: "cpu|memory|stress|utiliz"
    alert:
      AlarmName: "EKS-agenticops-chaos-lab-NodeCPU-High"
      NewStateValue: "ALARM"
      NewStateReason: "Node CPU utilization high in chaos-lab"
      Trigger: { MetricName: "node_cpu_utilization", Namespace: "ContainerInsights" }
  expect_fix: { kind: no_pod_label, namespace: chaos-lab, selector: "chaos=resource-stress" }
  timeout_perceive_s: 120
  timeout_resolve_s: 480

- id: netpol-block
  mode: assert
  description: NetworkPolicy blocks all ingress to backend
  inject:  "chaos/network-chaos.sh block"
  restore: "chaos/network-chaos.sh restore"
  perceive:
    title_pattern: "network|connection|backend|unhealthy|timeout"
    alert:
      AlarmName: "EKS-agenticops-chaos-lab-Backend-Unreachable"
      NewStateValue: "ALARM"
      NewStateReason: "Frontend cannot reach backend (connection refused/timeout)"
      Trigger: { MetricName: "backend_connection_errors", Namespace: "ContainerInsights" }
  expect_fix: { kind: no_networkpolicy, namespace: chaos-lab, name: chaos-block-backend }
  timeout_perceive_s: 120
  timeout_resolve_s: 480

- id: coredns-down
  mode: evidence
  description: CoreDNS scaled to 0 — cluster-wide DNS failures
  inject:  "e2e/scenarios/coredns-down.sh break"
  restore: "e2e/scenarios/coredns-down.sh restore"
  chat_prompt: "Investigate and fix the cluster-wide DNS resolution failures in the agenticops-chaos-lab cluster."
  timeout_evidence_s: 600

- id: service-deleted
  mode: evidence
  description: backend Service deleted — endpoints empty
  inject:  "e2e/scenarios/service-deleted.sh break"
  restore: "e2e/scenarios/service-deleted.sh restore"
  chat_prompt: "The backend service in namespace chaos-lab appears to be missing. Investigate and restore it."
  timeout_evidence_s: 600
```

- [ ] **Step 2: Validate YAML + required keys**

Run:
```bash
python3 -c "
import yaml
s = yaml.safe_load(open('infra/eks-chaos-lab/e2e/scenarios.yaml'))
assert isinstance(s, list) and len(s) == 8, len(s)
for x in s:
    assert x['mode'] in ('assert','evidence'), x['id']
    assert 'inject' in x and 'restore' in x, x['id']
    if x['mode']=='assert': assert 'perceive' in x and 'expect_fix' in x, x['id']
    else: assert 'chat_prompt' in x, x['id']
print('scenarios ok:', len(s))
"
```
Expected: `scenarios ok: 8`

- [ ] **Step 3: Commit**

```bash
git add infra/eks-chaos-lab/e2e/scenarios.yaml
git commit -m "feat(chaos-e2e): declarative scenario registry (6 assert + 2 evidence)"
```

---

## Task 9: `conftest.py` — fixtures + kubectl helpers + restore teardown

**Files:**
- Create: `infra/eks-chaos-lab/e2e/conftest.py`

**Interfaces:**
- Consumes: `AgenticOpsClient` (Task 7), `scenarios.yaml` (Task 8), env vars `AGENTICOPS_URL`, `AIOPS_ADMIN_EMAIL` (default `admin` — the app seeds the admin with email `"admin"`), `AIOPS_ADMIN_PASSWORD`, `CHAOS_LAB_DIR` (default = the eks-chaos-lab dir), `AWS_ACCOUNT_ID`.
- Produces: pytest fixtures/helpers used by both test modules:
  - `client` (session-scoped, logged-in `AgenticOpsClient`)
  - `assert_scenarios` / `evidence_scenarios` (lists filtered by mode; used by parametrization via `pytest_generate_tests`)
  - `run_chaos(rel_cmd: str) -> None` — runs a chaos script from `CHAOS_LAB_DIR`
  - `kubectl_json(args: str) -> dict` — `kubectl get ... -o json` parsed
  - `verify_fix(expect: dict) -> tuple[bool, str]` — checks the cluster end-state for each `expect_fix.kind`
  - `restore_and_wait(scenario: dict)` — runs `restore`, waits for green

- [ ] **Step 1: Write conftest.py**

```python
"""Pytest fixtures for the EKS chaos E2E harness."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

import pytest
import yaml

from client import AgenticOpsClient  # same dir; pytest adds rootdir to sys.path via conftest

E2E_DIR = pathlib.Path(__file__).resolve().parent
CHAOS_LAB_DIR = pathlib.Path(os.environ.get("CHAOS_LAB_DIR", str(E2E_DIR.parent)))
SCENARIOS = yaml.safe_load(open(E2E_DIR / "scenarios.yaml"))


def pytest_generate_tests(metafunc):
    if "assert_scenario" in metafunc.fixturenames:
        cases = [s for s in SCENARIOS if s["mode"] == "assert"]
        metafunc.parametrize("assert_scenario", cases, ids=[c["id"] for c in cases])
    if "evidence_scenario" in metafunc.fixturenames:
        cases = [s for s in SCENARIOS if s["mode"] == "evidence"]
        metafunc.parametrize("evidence_scenario", cases, ids=[c["id"] for c in cases])


@pytest.fixture(scope="session")
def client() -> AgenticOpsClient:
    base = os.environ.get("AGENTICOPS_URL", "http://localhost:8000")
    c = AgenticOpsClient(base)
    # The app seeds the admin user with email literally "admin" (see app.py
    # create_user(email="admin", ...)), NOT an @-address.
    email = os.environ.get("AIOPS_ADMIN_EMAIL", "admin")
    pw = os.environ.get("AIOPS_ADMIN_PASSWORD", "aiops2026")
    c.login(email, pw)
    acct = os.environ.get("AWS_ACCOUNT_ID")
    if acct:
        c.ensure_account("chaos-lab", acct, ["us-east-1"])
    return c


def run_chaos(rel_cmd: str) -> None:
    parts = rel_cmd.split()
    script = CHAOS_LAB_DIR / parts[0]
    subprocess.run(["bash", str(script), *parts[1:]], check=True,
                   cwd=str(CHAOS_LAB_DIR), timeout=300)


def kubectl_json(args: str) -> dict:
    out = subprocess.run(["kubectl", *args.split(), "-o", "json"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return {}
    return json.loads(out.stdout) if out.stdout.strip() else {}


def verify_fix(expect: dict) -> tuple[bool, str]:
    kind = expect["kind"]
    if kind == "replicas_min":
        d = kubectl_json(f"get deploy {expect['deployment']} -n {expect['namespace']}")
        n = (d.get("status", {}) or {}).get("availableReplicas", 0) or 0
        return n >= expect["min"], f"availableReplicas={n} (>= {expect['min']})"
    if kind == "image_not_contains":
        d = kubectl_json(f"get deploy {expect['deployment']} -n {expect['namespace']}")
        imgs = [c.get("image", "") for c in
                d.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])]
        bad = [i for i in imgs if expect["substring"] in i]
        return not bad, f"images={imgs}"
    if kind == "node_schedulable":
        d = kubectl_json("get nodes")
        unsched = [n["metadata"]["name"] for n in d.get("items", [])
                   if (n.get("spec", {}) or {}).get("unschedulable")]
        return not unsched, f"unschedulable={unsched}"
    if kind == "no_pod_label":
        d = kubectl_json(f"get pods -n {expect['namespace']} -l {expect['selector']}")
        items = d.get("items", [])
        return len(items) == 0, f"pods_with_label={len(items)}"
    if kind == "no_networkpolicy":
        d = kubectl_json(f"get networkpolicy -n {expect['namespace']}")
        names = [n["metadata"]["name"] for n in d.get("items", [])]
        return expect["name"] not in names, f"netpols={names}"
    if kind == "coredns_min":
        d = kubectl_json("get deploy coredns -n kube-system")
        n = (d.get("status", {}) or {}).get("availableReplicas", 0) or 0
        return n >= expect["min"], f"coredns availableReplicas={n}"
    if kind == "service_exists":
        d = kubectl_json(f"get svc {expect['name']} -n {expect['namespace']}")
        return bool(d.get("metadata")), f"service present={bool(d.get('metadata'))}"
    return False, f"unknown expect kind {kind}"


def restore_and_wait(scenario: dict) -> None:
    try:
        run_chaos(scenario["restore"])
    except Exception as e:  # noqa: BLE001 — restore must not mask the test result
        print(f"[restore] warning: {e}")
    time.sleep(5)
```

- [ ] **Step 2: Sanity import + parametrization check (offline)**

Run:
```bash
cd infra/eks-chaos-lab/e2e && python3 -c "import yaml,pathlib; s=yaml.safe_load(open('scenarios.yaml')); print('assert:',sum(x['mode']=='assert' for x in s),'evidence:',sum(x['mode']=='evidence' for x in s))"
```
Expected: `assert: 6 evidence: 2`

- [ ] **Step 3: py_compile conftest**

Run: `python -m py_compile infra/eks-chaos-lab/e2e/conftest.py && echo "compile ok"`
Expected: `compile ok`

- [ ] **Step 4: Commit**

```bash
git add infra/eks-chaos-lab/e2e/conftest.py
git commit -m "feat(chaos-e2e): pytest fixtures — client, chaos runner, verify_fix, restore"
```

---

## Task 10: `test_e2e_four_phases.py` — assert-mode four-phase test

**Files:**
- Create: `infra/eks-chaos-lab/e2e/test_e2e_four_phases.py`

**Interfaces:**
- Consumes: `client` fixture, `assert_scenario` param, `run_chaos`, `verify_fix`, `restore_and_wait` (Task 9); `AgenticOpsClient` methods + `PhaseTimeout` (Task 7).
- Produces: one parametrized test proving 感知→分析→解决→记录 per assert scenario.

- [ ] **Step 1: Write the test**

```python
"""Assert-mode E2E: inject → perceive → analyze → resolve → record → restore.

Requires a live cluster + a port-forwarded app (see run-e2e.sh). Not part of
offline CI. Each phase failure raises PhaseTimeout naming the failed phase.
"""
import time

import pytest

from client import PhaseTimeout
from conftest import run_chaos, verify_fix, restore_and_wait


def test_four_phases(client, assert_scenario, request):
    sc = assert_scenario
    # Clean start
    restore_and_wait(sc)

    try:
        # inject the fault
        run_chaos(sc["inject"])
        # Give the fault a moment to manifest before seeding perception.
        time.sleep(10)

        # ---- 感知 (perceive): seed a CloudWatch alert, then assert an issue appears
        client.send_cloudwatch_alert(sc["perceive"]["alert"])
        issue_id = client.wait_for_issue(
            sc["perceive"]["title_pattern"], timeout_s=sc["timeout_perceive_s"])

        # ---- 分析 (analyze): RCA attached
        analyze_deadline = time.monotonic() + 180
        while time.monotonic() < analyze_deadline and not client.has_rca(issue_id):
            time.sleep(5)
        assert client.has_rca(issue_id), f"[analyze] no RCA for issue {issue_id}"

        # ---- 解决 (resolve): issue resolved AND a fix plan executed AND cluster fixed
        status = client.wait_for_status(
            issue_id, {"resolved"}, timeout_s=sc["timeout_resolve_s"])
        assert status == "resolved"
        plan = client.get_fix_plan(issue_id)
        assert plan is not None, f"[resolve] no fix plan for issue {issue_id}"
        ok, detail = verify_fix(sc["expect_fix"])
        assert ok, f"[resolve] cluster not actually fixed: {detail}"

        # ---- 记录 (record): timeline has fix/resolve events
        timeline = client.get_timeline(issue_id)
        etypes = " ".join(str(e.get("event_type", "")) for e in timeline).lower()
        assert timeline, f"[record] empty timeline for issue {issue_id}"
        assert ("resolve" in etypes or "fix" in etypes or "execut" in etypes), \
            f"[record] no fix/resolve events in timeline: {etypes}"
    finally:
        restore_and_wait(sc)
```

- [ ] **Step 2: py_compile**

Run: `python -m py_compile infra/eks-chaos-lab/e2e/test_e2e_four_phases.py && echo "compile ok"`
Expected: `compile ok`

- [ ] **Step 3: Collection-only check (offline, no cluster)**

Run: `cd infra/eks-chaos-lab/e2e && python -m pytest test_e2e_four_phases.py --collect-only -q`
Expected: 6 collected items (`test_four_phases[scale-to-zero]` … `[netpol-block]`). (Collection must not require a cluster; the `client` fixture is only instantiated at run time.)

- [ ] **Step 4: Commit**

```bash
git add infra/eks-chaos-lab/e2e/test_e2e_four_phases.py
git commit -m "feat(chaos-e2e): assert-mode four-phase test (parametrized, phase-attributed)"
```

---

## Task 11: Evidence scenarios (scripts) + `test_e2e_evidence.py`

**Files:**
- Create: `infra/eks-chaos-lab/e2e/scenarios/coredns-down.sh`
- Create: `infra/eks-chaos-lab/e2e/scenarios/service-deleted.sh`
- Create: `infra/eks-chaos-lab/e2e/test_e2e_evidence.py`

**Interfaces:**
- Consumes: `client` fixture, `evidence_scenario` param, `run_chaos`, `restore_and_wait` (Task 9). Chat endpoints: `POST /api/chat/sessions` (body `{"name": ...}`) → `ChatSessionResponse` with string `session_id`; `POST /api/chat/sessions/{session_id}/messages` (body `{"content": ...}`, path uses the **string** `session_id`, not int `id`); `GET /api/reports`.
- Produces: two inject/restore scripts + a parametrized evidence test that captures transcript + report + timeline into `results/<id>/`.

- [ ] **Step 1: Write coredns-down.sh**

```bash
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
```

- [ ] **Step 2: Write service-deleted.sh**

```bash
#!/usr/bin/env bash
# Evidence scenario: delete the backend Service (endpoints go empty), and restore.
set -euo pipefail
NS="chaos-lab"
ACTION="${1:-}"
case "${ACTION}" in
  break)
    kubectl get svc backend -n "${NS}" -o yaml > /tmp/agenticops-backend-svc.yaml 2>/dev/null || true
    kubectl delete svc backend -n "${NS}" --ignore-not-found
    echo "backend Service deleted — frontend can no longer resolve it."
    ;;
  restore)
    if [[ -f /tmp/agenticops-backend-svc.yaml ]]; then
      kubectl apply -f /tmp/agenticops-backend-svc.yaml || true
    else
      kubectl expose deployment backend -n "${NS}" --name=backend --port=80 --target-port=8080 2>/dev/null || true
    fi
    echo "backend Service restored."
    ;;
  *) echo "Usage: service-deleted.sh [break|restore]"; exit 1;;
esac
```

- [ ] **Step 3: Write test_e2e_evidence.py**

```python
"""Evidence-mode E2E: drive the agent via chat, capture transcript + report.

Soft assertions only (a session completes, an artifact is produced). The
captured artifacts under results/<id>/ are the deliverable for human review.
"""
import json
import pathlib
import time

import requests

from conftest import run_chaos, restore_and_wait, E2E_DIR


def _post_chat_message(client, session_id, prompt) -> str:
    """POST a chat message and accumulate the (SSE or JSON) response as text."""
    url = f"{client.base_url}/api/chat/sessions/{session_id}/messages"
    r = requests.post(url, headers=client._headers(),
                      json={"content": prompt}, stream=True, timeout=600)
    r.raise_for_status()
    chunks = []
    for line in r.iter_lines(decode_unicode=True):
        if line:
            chunks.append(line)
    return "\n".join(chunks)


def test_evidence(client, evidence_scenario):
    sc = evidence_scenario
    results = E2E_DIR / "results" / sc["id"]
    results.mkdir(parents=True, exist_ok=True)
    restore_and_wait(sc)

    try:
        run_chaos(sc["inject"])
        time.sleep(10)

        # NOTE: create body field is `name` (ChatSessionCreate.name); the messages
        # endpoint keys off the STRING `session_id` (UUID), NOT the int `id`.
        session = client.post("/api/chat/sessions", json={"name": f"e2e-{sc['id']}"})
        session_id = session.get("session_id")
        assert session_id, f"no session_id in {session}"

        transcript = _post_chat_message(client, session_id, sc["chat_prompt"])
        (results / "transcript.md").write_text(transcript)

        # Capture newest report as evidence (best-effort).
        try:
            reports = client.get("/api/reports")
            items = reports if isinstance(reports, list) else reports.get("items", [])
            (results / "reports.json").write_text(json.dumps(items[:5], indent=2, default=str))
        except Exception as e:  # noqa: BLE001
            (results / "reports.json").write_text(f"error: {e}")

        # Soft guarantees.
        assert transcript.strip(), "[evidence] empty transcript"
        assert (results / "transcript.md").exists()
    finally:
        restore_and_wait(sc)
```

- [ ] **Step 4: Syntax + compile checks**

Run:
```bash
bash -n infra/eks-chaos-lab/e2e/scenarios/coredns-down.sh
bash -n infra/eks-chaos-lab/e2e/scenarios/service-deleted.sh
python -m py_compile infra/eks-chaos-lab/e2e/test_e2e_evidence.py
cd infra/eks-chaos-lab/e2e && python -m pytest test_e2e_evidence.py --collect-only -q
echo "all ok"
```
Expected: 2 collected items (`test_evidence[coredns-down]`, `test_evidence[service-deleted]`) then `all ok`.

- [ ] **Step 5: Commit**

```bash
git add infra/eks-chaos-lab/e2e/scenarios/ infra/eks-chaos-lab/e2e/test_e2e_evidence.py
git commit -m "feat(chaos-e2e): evidence scenarios (coredns, service-deleted) + chat-capture test"
```

---

## Task 12: `run-e2e.sh` + results gitignore + README + WORKFLOW docs

**Files:**
- Create: `infra/eks-chaos-lab/e2e/run-e2e.sh`
- Create: `infra/eks-chaos-lab/e2e/results/.gitkeep`
- Modify: `.gitignore` (ignore `infra/eks-chaos-lab/e2e/results/*` except `.gitkeep`)
- Create: `infra/eks-chaos-lab/e2e/README.md`
- Modify: `docs/WORKFLOW.md` (append a "Chaos E2E runbook" section)

**Interfaces:**
- Consumes: everything above; assumes `kubectl` context = the chaos cluster and the app is deployed (Task 6).
- Produces: the single remote entrypoint. No downstream consumer.

- [ ] **Step 1: Write run-e2e.sh**

```bash
#!/usr/bin/env bash
# Remote-server entrypoint for the EKS chaos E2E suite.
# Tunnels to the ClusterIP app via port-forward, runs pytest, always restores.
# Usage: bash run-e2e.sh [--assert-only|--evidence-only] [-- <pytest args>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHAOS_LAB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NS="agenticops"
LOCAL_PORT="${LOCAL_PORT:-8000}"
SELECT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --assert-only)   SELECT="test_e2e_four_phases.py"; shift;;
    --evidence-only) SELECT="test_e2e_evidence.py"; shift;;
    --) shift; break;;
    *) break;;
  esac
done

export CHAOS_LAB_DIR
export AGENTICOPS_URL="http://localhost:${LOCAL_PORT}"
export AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"

echo "[preflight] cluster + app reachable?"
kubectl get svc agenticops -n "${NS}" >/dev/null

echo "[tunnel] kubectl port-forward svc/agenticops ${LOCAL_PORT}:8000"
kubectl port-forward "svc/agenticops" -n "${NS}" "${LOCAL_PORT}:8000" >/tmp/agenticops-pf.log 2>&1 &
PF_PID=$!
cleanup() {
  kill "${PF_PID}" 2>/dev/null || true
  bash "${CHAOS_LAB_DIR}/chaos/restore-all.sh" || true
}
trap cleanup EXIT

# Wait for the tunnel + app health.
for i in $(seq 1 30); do
  if curl -sf "${AGENTICOPS_URL}/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -sf "${AGENTICOPS_URL}/api/health" >/dev/null || { echo "app health check failed"; exit 1; }

echo "[run] pytest"
cd "${SCRIPT_DIR}"
python -m pytest ${SELECT} -v --junitxml=results/junit.xml "$@" || true

echo "[done] artifacts under ${SCRIPT_DIR}/results/"
```

- [ ] **Step 2: Add results/.gitkeep and .gitignore rule**

Create `infra/eks-chaos-lab/e2e/results/.gitkeep` (empty). Append to `.gitignore`:

```
# Chaos E2E run artifacts (keep the dir, ignore contents)
infra/eks-chaos-lab/e2e/results/*
!infra/eks-chaos-lab/e2e/results/.gitkeep
```

- [ ] **Step 3: Write README.md**

```markdown
# EKS Chaos E2E Harness

Proves the AgenticOps 感知→分析→解决→记录 loop against injected faults on the
`agenticops-chaos-lab` EKS cluster, with the app deployed **internal-only**
(ClusterIP — never public).

## Prerequisites
- `kubectl` context pointing at `agenticops-chaos-lab` (us-east-1)
- `aws` CLI creds for the lab account; `python` with `requests`, `pyyaml`, `pytest`
- App deployed in-cluster: `bash ../agenticops/deploy-app.sh`
- Cluster + workloads + alarms up: `bash ../setup.sh`

## Run
```bash
export AIOPS_ADMIN_PASSWORD=...        # matches deploy-app.sh --admin-password
bash run-e2e.sh                        # all scenarios
bash run-e2e.sh --assert-only          # deterministic pass/fail only
bash run-e2e.sh --evidence-only        # chat + report capture only
```
`run-e2e.sh` opens a `kubectl port-forward` tunnel, runs pytest, writes
`results/junit.xml` + per-scenario evidence, and always runs `restore-all.sh`.

## Phases asserted (assert mode)
| Phase | Assertion |
|-------|-----------|
| 感知 perceive | a HealthIssue matching the scenario appears (`/api/health-issues`) |
| 分析 analyze  | an RCAResult is attached (`/api/health-issues/{id}/rca`) |
| 解决 resolve  | issue → `resolved`, a FixPlan executed, cluster end-state fixed (kubectl) |
| 记录 record   | pipeline timeline has fix/resolve events (`/api/health-issues/{id}/timeline`) |

## Scenarios
6 assert (scale-to-zero, bad-image, crashloop-config, node-drained,
resource-stress, netpol-block) + 2 evidence (coredns-down, service-deleted).
Add more by appending to `scenarios.yaml`.

## Safety
- App is ClusterIP-only; the sole ingress is the port-forward tunnel.
- Every scenario restores on teardown; `restore-all.sh` runs at the very end.
```

- [ ] **Step 4: Append the runbook to docs/WORKFLOW.md**

Add a section `## Chaos E2E Runbook` summarizing: deploy the app in-cluster (`agenticops/deploy-app.sh`), run `e2e/run-e2e.sh` from the remote server, interpret `results/`. Link to `infra/eks-chaos-lab/e2e/README.md`. (Match the existing WORKFLOW.md heading style — read the file first and mirror it.)

- [ ] **Step 5: Validate**

Run:
```bash
bash -n infra/eks-chaos-lab/e2e/run-e2e.sh && echo "syntax ok"
git check-ignore infra/eks-chaos-lab/e2e/results/foo.json && echo "results ignored"
git check-ignore infra/eks-chaos-lab/e2e/results/.gitkeep; echo "gitkeep exit=$?"   # expect non-zero (NOT ignored)
```
Expected: `syntax ok`, `results ignored`, and `.gitkeep` NOT ignored (exit 1).

- [ ] **Step 6: Commit**

```bash
git add infra/eks-chaos-lab/e2e/run-e2e.sh infra/eks-chaos-lab/e2e/results/.gitkeep infra/eks-chaos-lab/e2e/README.md .gitignore docs/WORKFLOW.md
git commit -m "feat(chaos-e2e): run-e2e.sh remote entrypoint + README + WORKFLOW runbook"
```

---

## Task 13: Live end-to-end dry run + tuning (manual, gated)

**Files:** none (operational task; may adjust timeouts in `scenarios.yaml` and alert payloads only).

**Interfaces:** Consumes the whole system. This is the real E2E — run only after the user confirms it's time to touch the live cluster (per the test-before-commit / confirm-before-outward-op rules).

- [ ] **Step 1: Bring up the lab (if not already up)**

Run: `bash infra/eks-chaos-lab/setup.sh` (creates cluster, workloads, 6 alarms). Then `bash infra/eks-chaos-lab/verify/verify-agenticops.sh`.
Expected: `7/7 passed — ALL OK`.

- [ ] **Step 2: Deploy the app in-cluster**

Run: `bash infra/eks-chaos-lab/agenticops/deploy-app.sh --admin-password <pw>`
Expected: `deployment "agenticops" successfully rolled out`, then the printed port-forward hint.

- [ ] **Step 3: Smoke the tunnel + auth + account**

Run:
```bash
kubectl port-forward svc/agenticops -n agenticops 8000:8000 &
sleep 5 && curl -s localhost:8000/api/health
```
Expected: health JSON `ok`. Then confirm login works with the admin password.

- [ ] **Step 4: Run one assert scenario, tune timeouts**

Run: `cd infra/eks-chaos-lab/e2e && AIOPS_ADMIN_PASSWORD=<pw> bash run-e2e.sh --assert-only -- -k scale-to-zero`
Expected: PASS. If a phase times out, the `PhaseTimeout`/assert message names the phase — bump that scenario's `timeout_*_s` or fix the alert payload/title_pattern, then re-run. Adjust only `scenarios.yaml`.

- [ ] **Step 5: Full assert run, then evidence run**

Run: `bash run-e2e.sh --assert-only` then `bash run-e2e.sh --evidence-only`.
Expected: assert suite green; evidence `results/<id>/transcript.md` + `reports.json` populated. Review evidence artifacts manually.

- [ ] **Step 6: Record results + commit any timeout tuning**

If `scenarios.yaml` timeouts/payloads changed:
```bash
git add infra/eks-chaos-lab/e2e/scenarios.yaml
git commit -m "test(chaos-e2e): tune scenario timeouts/alerts from live run"
```
Report the junit summary + evidence paths to the user. **Do not `git push`** — the user pushes after confirming (per project rules).

---

## Self-Review

**1. Spec coverage:**
- Internal-only app (ClusterIP, no public) → Tasks 5 (service.yaml), 6 (deploy guard), 12 (README/safety). ✓
- In-cluster deploy on existing cluster → Tasks 2–6. ✓
- Two identities (IRSA + in-cluster kubeconfig) → Tasks 1 (IRSA policy), 5 (kubeconfig init), plus `environment` account registration in Task 7/9. ✓
- Scoped least-privilege RBAC (no cluster-admin) → Task 3 (+ guard in Step 2). ✓
- Remote-runnable harness via port-forward → Task 12. ✓
- Four-phase asserts (感知/分析/解决/记录) → Task 10 + `verify_fix` Task 9. ✓
- Evidence mode (chat + report capture) → Task 11. ✓
- More scenarios (6→8, extensible via YAML) → Tasks 8, 11. ✓
- Reuse existing chaos scripts/image/setup → Tasks 6, 8, 9. ✓
- Offline unit tests in repo `tests/`; live E2E separate → Tasks 7, 13. ✓
- Fail-closed restore → Tasks 9 (`restore_and_wait`), 10/11 (`finally`), 12 (`trap` + restore-all). ✓
- Perception entry explicit (webhook default) → Task 8 alert payloads, Task 10. ✓

**2. Placeholder scan:** `__IRSA_ROLE_ARN__` and `__IMAGE__` are intentional sed-substituted tokens (documented in Tasks 2/5/6), not TODOs. `CHANGE_ME` in the Secret *template* is intentional (real value injected by deploy-app.sh). No "TBD/implement later" steps; every code step shows full code. ✓

**3. Type consistency:** `AgenticOpsClient` method names/signatures defined in Task 7 match all call sites in Tasks 9–11 (`login`, `send_cloudwatch_alert`, `wait_for_issue`, `has_rca`, `wait_for_status`, `get_fix_plan`, `get_timeline`, `ensure_account`, `_headers`, `base_url`, `post`, `get`). `verify_fix` `expect_fix.kind` values in Task 8 (`replicas_min`, `image_not_contains`, `node_schedulable`, `no_pod_label`, `no_networkpolicy`) all handled in Task 9. `PhaseTimeout(phase, detail)` consistent between Task 7 def and Task 10 use. Namespaces (`agenticops`, `chaos-lab`, `kube-system`) consistent across Tasks 3/5/8/9. ✓
