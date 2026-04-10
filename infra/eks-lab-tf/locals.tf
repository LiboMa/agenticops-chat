locals {
  azs = ["${var.region}a", "${var.region}b", "${var.region}c"]

  tags = merge(var.tags, {
    Project     = "agenticops"
    Environment = "lab"
    ManagedBy   = "terraform"
  })
}
