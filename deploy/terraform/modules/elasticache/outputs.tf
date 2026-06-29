output "primary_endpoint" { value = aws_elasticache_replication_group.this.primary_endpoint_address }
output "redis_url" {
  value     = "rediss://:${random_password.auth.result}@${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
  sensitive = true
}
