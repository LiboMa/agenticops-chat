# AgenticOps — Build & Deploy
REGION     ?= ap-southeast-1
PROJECT    ?= agenticops
TAG        ?= $(shell git rev-parse --short HEAD)
ECR_REPO   ?= $(shell cd iac/ec2 && terraform output -raw ecr_repository_url 2>/dev/null || echo "")

.PHONY: build push deploy-ec2 deploy-ecs deploy-eks clean

# --- Docker ---
build:
	docker build -t $(PROJECT):$(TAG) -t $(PROJECT):latest .

push:
	@if [ -z "$(ECR_REPO)" ]; then echo "ERROR: ECR_REPO not set. Run terraform apply first or set ECR_REPO env var."; exit 1; fi
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(ECR_REPO)
	docker tag $(PROJECT):$(TAG) $(ECR_REPO):$(TAG)
	docker tag $(PROJECT):latest $(ECR_REPO):latest
	docker push $(ECR_REPO):$(TAG)
	docker push $(ECR_REPO):latest
	@echo "Pushed: $(ECR_REPO):$(TAG)"

# --- Terraform Deploy ---
deploy-ec2:
	cd iac/ec2 && terraform init -upgrade && terraform apply

deploy-ecs:
	cd iac/ecs && terraform init -upgrade && terraform apply

deploy-eks:
	cd iac/eks && terraform init -upgrade && terraform apply

# --- Cleanup ---
clean:
	docker rmi $(PROJECT):$(TAG) $(PROJECT):latest 2>/dev/null || true
