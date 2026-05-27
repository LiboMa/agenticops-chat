variable "project_name" {
  type = string
}

variable "service" {
  description = "Service type: ec2, ecs, or eks"
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
