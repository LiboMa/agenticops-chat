locals {
  password = var.enabled ? (var.password != "" ? var.password : random_password.this[0].result) : ""
}

resource "random_password" "this" {
  count   = var.enabled && var.password == "" ? 1 : 0
  length  = 24
  special = false
}

resource "aws_db_subnet_group" "this" {
  count      = var.enabled ? 1 : 0
  name       = "${var.project_name}-db-subnet"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "rds" {
  count       = var.enabled ? 1 : 0
  name_prefix = "${var.project_name}-rds-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = var.allowed_security_group_id != "" ? [var.allowed_security_group_id] : []
    cidr_blocks     = var.allowed_security_group_id == "" ? ["10.0.0.0/8"] : []
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
  lifecycle { create_before_destroy = true }
}

resource "aws_db_instance" "this" {
  count                  = var.enabled ? 1 : 0
  identifier             = "${var.project_name}-db"
  engine                 = "postgres"
  engine_version         = "16.4"
  instance_class         = var.instance_class
  allocated_storage      = var.allocated_storage
  db_name                = "agenticops"
  username               = "agenticops"
  password               = local.password
  db_subnet_group_name   = aws_db_subnet_group.this[0].name
  vpc_security_group_ids = [aws_security_group.rds[0].id]
  skip_final_snapshot    = true
  publicly_accessible    = false
  storage_encrypted      = true
  tags                   = var.tags
}
