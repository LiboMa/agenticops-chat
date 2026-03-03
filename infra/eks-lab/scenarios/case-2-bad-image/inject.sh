#!/usr/bin/env bash
# Case 2: Bad Image → ImagePullBackOff
# Inject: Set productcatalogservice image to a nonexistent tag
# Expected: KubeDeploymentReplicasMismatch alert (~5 min)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 2: Bad Image (productcatalogservice) ===${NC}\n"

# Save current image for verification later
CURRENT_IMAGE=$(kubectl get deploy productcatalogservice -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "unknown")
echo "$CURRENT_IMAGE" > /tmp/case2-original-image.txt
report_info "Original image: ${CURRENT_IMAGE}"

# Extract repo (everything before the last colon)
IMAGE_REPO="${CURRENT_IMAGE%:*}"
BAD_TAG="v999.0.0-nonexistent"

# Inject: set image to nonexistent tag
report_info "Setting productcatalogservice image to ${IMAGE_REPO}:${BAD_TAG}..."
kubectl set image deploy/productcatalogservice -n online-boutique \
    server="${IMAGE_REPO}:${BAD_TAG}"

report_pass "Fault injected — productcatalogservice image=${IMAGE_REPO}:${BAD_TAG}"
report_info "Expected alerts: KubeDeploymentReplicasMismatch (~5 min)"
