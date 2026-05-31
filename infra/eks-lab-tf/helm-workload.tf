resource "helm_release" "online_boutique" {
  namespace  = kubernetes_namespace.online_boutique.metadata[0].name
  name       = "online-boutique"
  repository = "oci://us-docker.pkg.dev/online-boutique-ci/charts"
  chart      = "onlineboutique"
  version    = "0.10.1"

  timeout = 600
  wait    = true

  values = [file("${path.module}/values/online-boutique.yaml")]

  depends_on = [helm_release.otel_collector]
}
