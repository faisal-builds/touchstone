output "endpoint" { value = aws_db_instance.this.address }
output "port" { value = aws_db_instance.this.port }
output "sqlalchemy_url" {
  value     = "postgresql+asyncpg://${var.master_username}:${random_password.master.result}@${aws_db_instance.this.address}:${aws_db_instance.this.port}/${var.database_name}"
  sensitive = true
}
