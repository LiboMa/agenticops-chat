# AgenticOps — Build & Deploy
REGION     ?= ap-southeast-1
PROJECT    ?= agenticops
TAG        ?= $(shell git rev-parse --short HEAD)
TF_DIR     ?= iac/ec2

.PHONY: build push deploy-ec2 deploy-ecs deploy-eks destroy clean

# --- Docker ---
build:
	docker build -t $(PROJECT):$(TAG) -t $(PROJECT):latest .

push:
	$(eval ECR_REPO := $(shell cd $(TF_DIR) && terraform output -raw ecr_repository_url 2>/dev/null))
	@if [ -z "$(ECR_REPO)" ]; then echo "ERROR: ECR_REPO not available. Run deploy first."; exit 1; fi
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(ECR_REPO)
	docker tag $(PROJECT):$(TAG) $(ECR_REPO):$(TAG)
	docker tag $(PROJECT):latest $(ECR_REPO):latest
	docker push $(ECR_REPO):$(TAG)
	docker push $(ECR_REPO):latest
	@echo "Pushed: $(ECR_REPO):$(TAG)"

# --- Full Deploy (solves chicken-and-egg: ECR first, then build+push, then full apply) ---
deploy-ec2:
	@echo "=== Phase 1: Create ECR ==="
	cd iac/ec2 && terraform init -upgrade && terraform apply -target=module.ecr -auto-approve
	@echo "=== Phase 2: Build & Push Image ==="
	$(MAKE) TF_DIR=iac/ec2 build push
	@echo "=== Phase 3: Deploy All ==="
	cd iac/ec2 && terraform apply -auto-approve
	@echo "=== Done ==="
	@cd iac/ec2 && terraform output

deploy-ecs:
	@echo "=== Phase 1: Create ECR ==="
	cd iac/ecs && terraform init -upgrade && terraform apply -target=module.ecr -auto-approve
	@echo "=== Phase 2: Build & Push Image ==="
	$(MAKE) TF_DIR=iac/ecs build push
	@echo "=== Phase 3: Deploy All ==="
	cd iac/ecs && terraform apply -auto-approve
	@echo "=== Done ==="
	@cd iac/ecs && terraform output

deploy-eks:
	@echo "=== Phase 1: Create ECR ==="
	cd iac/eks && terraform init -upgrade && terraform apply -target=module.ecr -auto-approve
	@echo "=== Phase 2: Build & Push Image ==="
	$(MAKE) TF_DIR=iac/eks build push
	@echo "=== Phase 3: Deploy All ==="
	cd iac/eks && terraform apply -auto-approve
	@echo "=== Done ==="
	@cd iac/eks && terraform output

# --- Destroy ---
destroy-ec2:
	cd iac/ec2 && terraform destroy -auto-approve

destroy-ecs:
	cd iac/ecs && terraform destroy -auto-approve

destroy-eks:
	cd iac/eks && terraform destroy -auto-approve

# --- Cleanup local images ---
clean:
	docker rmi $(PROJECT):$(TAG) $(PROJECT):latest 2>/dev/null || true
