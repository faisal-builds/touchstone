output "region" {
  value       = var.region
  description = "AWS region."
}

output "cluster_name" {
  value       = module.eks.cluster_name
  description = "EKS cluster name (for `aws eks update-kubeconfig`)."
}

output "cluster_endpoint" {
  value       = module.eks.cluster_endpoint
  description = "EKS API server endpoint."
}

output "rds_endpoint" {
  value       = module.rds.endpoint
  description = "RDS PostgreSQL endpoint host."
}

output "elasticache_endpoint" {
  value       = module.elasticache.primary_endpoint
  description = "ElastiCache Redis primary endpoint host."
}

output "artifact_bucket" {
  value       = module.s3.artifact_bucket_name
  description = "S3 artifact bucket name (-> Helm externalServices.artifactStoreUri)."
}

output "irsa_app_role_arn" {
  value       = module.iam.app_role_arn
  description = "IRSA role ARN for the app ServiceAccount (-> Helm serviceAccount.annotations)."
}

output "irsa_external_secrets_role_arn" {
  value       = module.iam.external_secrets_role_arn
  description = "IRSA role ARN for the External Secrets Operator."
}

output "acm_certificate_arn" {
  value       = aws_acm_certificate.main.arn
  description = "ACM certificate ARN (-> Helm ingress.tls.certificateArn)."
}

output "secrets_manager_key" {
  value       = aws_secretsmanager_secret.app.name
  description = "Secrets Manager key (-> Helm secrets.externalSecretRemoteKey)."
}
