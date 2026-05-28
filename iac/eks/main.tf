locals {
  tags         = { Project = var.project_name, ManagedBy = "terraform" }
  database_url = var.db_backend == "rds" ? module.rds.database_url : "sqlite:////app/data/agenticops.db"
  image_uri    = "${module.ecr.repository_url}:${var.image_tag}"
}

data "aws_caller_identity" "current" {}

module "ecr" {
  source = "../modules/ecr"
  name   = var.project_name
  tags   = local.tags
}

module "vpc" {
  source             = "../modules/vpc"
  project_name       = var.project_name
  vpc_id             = var.vpc_id
  public_subnet_ids  = var.public_subnet_ids
  private_subnet_ids = var.private_subnet_ids
  tags               = local.tags
}

module "rds" {
  source       = "../modules/rds"
  enabled      = var.db_backend == "rds"
  project_name = var.project_name
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnet_ids
  tags         = local.tags
}

# --- Kubernetes Resources ---
resource "kubernetes_namespace" "this" {
  metadata {
    name = var.namespace
  }
}

resource "kubernetes_secret" "app" {
  metadata {
    name      = "${var.project_name}-env"
    namespace = kubernetes_namespace.this.metadata[0].name
  }

  data = {
    AIOPS_ADMIN_PASSWORD = var.admin_password
    AIOPS_DATABASE_URL   = local.database_url
  }
}

resource "kubernetes_config_map" "app" {
  metadata {
    name      = "${var.project_name}-config"
    namespace = kubernetes_namespace.this.metadata[0].name
  }

  data = {
    AIOPS_DEPLOYMENT_PROFILE      = "cloud"
    AIOPS_BEDROCK_REGION          = var.bedrock_region
    AIOPS_BEDROCK_MODEL_ID        = var.bedrock_model
    AIOPS_BEDROCK_MODEL_ID_STRONG = var.bedrock_model_strong
    AIOPS_BEDROCK_MODEL_ID_CHEAP  = var.bedrock_model_cheap
    AIOPS_API_AUTH_ENABLED        = "true"
    AIOPS_REPORT_STORAGE          = "s3"
    AIOPS_REPORT_S3_BUCKET        = "${var.project_name}-reports-${data.aws_caller_identity.current.account_id}"
    AIOPS_S3_REGION               = var.region
  }
}

resource "kubernetes_deployment" "app" {
  metadata {
    name      = var.project_name
    namespace = kubernetes_namespace.this.metadata[0].name
    labels    = { app = var.project_name }
  }

  spec {
    replicas = var.replicas

    selector {
      match_labels = { app = var.project_name }
    }

    template {
      metadata {
        labels = { app = var.project_name }
      }

      spec {
        node_selector = length(var.node_selector) > 0 ? var.node_selector : null

        container {
          name  = var.project_name
          image = local.image_uri

          port {
            container_port = 8000
          }

          env_from {
            config_map_ref { name = kubernetes_config_map.app.metadata[0].name }
          }

          env_from {
            secret_ref { name = kubernetes_secret.app.metadata[0].name }
          }

          resources {
            requests = { cpu = "500m", memory = "1Gi" }
            limits   = { cpu = "2000m", memory = "4Gi" }
          }

          liveness_probe {
            http_get {
              path = "/api/health"
              port = 8000
            }
            initial_delay_seconds = 15
            period_seconds        = 30
          }

          readiness_probe {
            http_get {
              path = "/api/health"
              port = 8000
            }
            initial_delay_seconds = 10
            period_seconds        = 10
          }

          volume_mount {
            name       = "data"
            mount_path = "/app/data"
          }
        }

        volume {
          name = "data"
          empty_dir {}
        }
      }
    }
  }
}

resource "kubernetes_service" "app" {
  metadata {
    name      = var.project_name
    namespace = kubernetes_namespace.this.metadata[0].name
    annotations = var.acm_cert_arn != "" ? {
      "service.beta.kubernetes.io/aws-load-balancer-type"            = "external"
      "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type" = "ip"
      "service.beta.kubernetes.io/aws-load-balancer-scheme"          = var.alb_internal ? "internal" : "internet-facing"
      "service.beta.kubernetes.io/aws-load-balancer-ssl-cert"        = var.acm_cert_arn
      "service.beta.kubernetes.io/aws-load-balancer-ssl-ports"       = "443"
    } : {}
  }

  spec {
    selector = { app = var.project_name }
    type     = var.acm_cert_arn != "" ? "LoadBalancer" : "ClusterIP"

    port {
      port        = var.acm_cert_arn != "" ? 443 : 8000
      target_port = 8000
      protocol    = "TCP"
    }
  }
}
