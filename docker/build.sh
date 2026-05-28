#!/bin/bash
# =============================================================================
# AgenticOps Docker Build & Push
#
# Usage:
#   ./docker/build.sh                    # Build only (tag: latest + git SHA)
#   ./docker/build.sh push               # Build + push to ECR
#   ./docker/build.sh push <ecr-repo>    # Build + push to specified ECR repo
#
# Environment:
#   AWS_REGION   - ECR region (default: ap-southeast-1)
#   IMAGE_TAG    - Override tag (default: git short SHA)
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."  # Always run from project root

PROJECT="agenticops"
TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
REGION="${AWS_REGION:-ap-southeast-1}"
DOCKERFILE="docker/Dockerfile"

echo "=== Building $PROJECT:$TAG ==="
docker build -f "$DOCKERFILE" -t "$PROJECT:$TAG" -t "$PROJECT:latest" .

echo "Image: $PROJECT:$TAG ($(docker images $PROJECT:$TAG --format '{{.Size}}'))"

# --- Push if requested ---
if [ "${1:-}" = "push" ]; then
    ECR_REPO="${2:-}"

    if [ -z "$ECR_REPO" ]; then
        # Auto-detect from terraform output
        for tf_dir in iac/ec2 iac/ecs iac/eks; do
            if [ -f "$tf_dir/terraform.tfstate" ]; then
                ECR_REPO=$(cd "$tf_dir" && terraform output -raw ecr_repository_url 2>/dev/null || echo "")
                [ -n "$ECR_REPO" ] && break
            fi
        done
    fi

    if [ -z "$ECR_REPO" ]; then
        echo "ERROR: No ECR repo found. Provide as argument or run terraform apply first."
        echo "Usage: ./docker/build.sh push <ecr-repo-url>"
        exit 1
    fi

    REGISTRY=$(echo "$ECR_REPO" | cut -d'/' -f1)
    echo "=== Pushing to $ECR_REPO ==="
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
    docker tag "$PROJECT:$TAG" "$ECR_REPO:$TAG"
    docker tag "$PROJECT:latest" "$ECR_REPO:latest"
    docker push "$ECR_REPO:$TAG"
    docker push "$ECR_REPO:latest"
    echo "=== Pushed: $ECR_REPO:$TAG ==="
fi
