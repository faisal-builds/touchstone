# Root module — wires the Touchstone production infrastructure together.

locals {
  name = "touchstone-${var.environment}"
  tags = merge(var.tags, { Stack = local.name })
}

module "vpc" {
  source                  = "./modules/vpc"
  name                    = local.name
  vpc_cidr                = var.vpc_cidr
  availability_zone_count = var.availability_zone_count
  tags                    = local.tags
}

module "eks" {
  source             = "./modules/eks"
  name               = local.name
  cluster_version    = var.cluster_version
  private_subnet_ids = module.vpc.private_subnet_ids
  tags               = local.tags
}

module "s3" {
  source = "./modules/s3"
  name   = local.name
  tags   = local.tags
}

module "iam" {
  source              = "./modules/iam"
  name                = local.name
  oidc_provider_arn   = module.eks.oidc_provider_arn
  oidc_provider_url   = module.eks.oidc_provider_url
  artifact_bucket_arn = module.s3.artifact_bucket_arn
  secrets_manager_arn = aws_secretsmanager_secret.app.arn
  tags                = local.tags
}

module "rds" {
  source              = "./modules/rds"
  name                = local.name
  engine_version      = var.postgres_version
  instance_class      = var.postgres_instance_class
  allocated_storage   = var.postgres_allocated_storage
  vpc_id              = module.vpc.vpc_id
  database_subnet_ids = module.vpc.database_subnet_ids
  allowed_cidr_blocks = module.vpc.private_subnet_cidrs
  tags                = local.tags
}

module "elasticache" {
  source              = "./modules/elasticache"
  name                = local.name
  node_type           = var.redis_node_type
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.database_subnet_ids
  allowed_cidr_blocks = module.vpc.private_subnet_cidrs
  tags                = local.tags
}

# --- TLS certificate for the public endpoints (validated via DNS) -----------
resource "aws_acm_certificate" "main" {
  domain_name               = var.domain_name
  subject_alternative_names = ["*.${var.domain_name}"]
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
  }
  tags = local.tags
}

# --- Application secret bundle (consumed by External Secrets Operator) -------
resource "random_password" "jwt_secret" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name        = "touchstone/${var.environment}"
  description = "Touchstone application secrets (JWT, DB URLs, API keys)."
  kms_key_id  = aws_kms_key.secrets.id
  tags        = local.tags
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    TOUCHSTONE_JWT_SECRET          = random_password.jwt_secret.result
    TOUCHSTONE_RHD_JWT_SECRET      = random_password.jwt_secret.result
    TOUCHSTONE_DATABASE_URL        = module.rds.sqlalchemy_url
    TOUCHSTONE_VERIFY_DATABASE_URL = module.rds.sqlalchemy_url
    TOUCHSTONE_RISK_DATABASE_URL   = module.rds.sqlalchemy_url
    TOUCHSTONE_AUDIT_DATABASE_URL  = module.rds.sqlalchemy_url
    TOUCHSTONE_RHD_DATABASE_URL    = module.rds.sqlalchemy_url
    TOUCHSTONE_REDIS_URL           = module.elasticache.redis_url
  })
}

resource "aws_kms_key" "secrets" {
  description             = "${local.name} Secrets Manager encryption key"
  deletion_window_in_days = 14
  enable_key_rotation     = true
  tags                    = local.tags
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${local.name}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}
