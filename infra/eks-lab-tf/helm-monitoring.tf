# ----- Namespaces -----
resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
    labels = {
      project = "agenticops"
    }
  }

  depends_on = [module.eks]
}

resource "kubernetes_namespace" "online_boutique" {
  metadata {
    name = "online-boutique"
    labels = {
      project = "agenticops"
    }
  }

  depends_on = [module.eks]
}

# ----- gp3 StorageClass -----
resource "kubernetes_storage_class" "gp3" {
  metadata {
    name = "gp3"
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy         = "Delete"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type   = "gp3"
    fsType = "ext4"
  }

  depends_on = [module.eks]
}

# ----- kube-prometheus-stack -----
resource "helm_release" "prometheus" {
  namespace  = kubernetes_namespace.monitoring.metadata[0].name
  name       = "prometheus"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = "72.3.0"

  timeout = 600
  wait    = true

  values = [file("${path.module}/values/prometheus.yaml")]

  # Inject Grafana password from variable
  set_sensitive {
    name  = "grafana.adminPassword"
    value = var.grafana_admin_password
  }

  # Conditionally inject AlertManager webhook
  dynamic "set" {
    for_each = var.alertmanager_webhook_url != "" ? [1] : []
    content {
      name  = "alertmanager.config.receivers[1].webhook_configs[0].url"
      value = var.alertmanager_webhook_url
    }
  }

  dynamic "set" {
    for_each = var.alertmanager_webhook_url != "" ? [1] : []
    content {
      name  = "alertmanager.config.receivers[1].webhook_configs[0].send_resolved"
      value = "true"
    }
  }

  depends_on = [kubernetes_storage_class.gp3]
}

# ----- Jaeger -----
resource "helm_release" "jaeger" {
  namespace  = kubernetes_namespace.monitoring.metadata[0].name
  name       = "jaeger"
  repository = "https://jaegertracing.github.io/helm-charts"
  chart      = "jaeger"
  version    = "3.4.1"

  timeout = 300
  wait    = true

  values = [file("${path.module}/values/jaeger.yaml")]

  depends_on = [helm_release.prometheus]
}

# ----- OpenTelemetry Collector -----
resource "helm_release" "otel_collector" {
  namespace  = kubernetes_namespace.monitoring.metadata[0].name
  name       = "otel-collector"
  repository = "https://open-telemetry.github.io/opentelemetry-helm-charts"
  chart      = "opentelemetry-collector"
  version    = "0.115.0"

  timeout = 300
  wait    = true

  values = [file("${path.module}/values/otel-collector.yaml")]

  depends_on = [helm_release.prometheus, helm_release.jaeger]
}
