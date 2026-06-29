output "artifact_bucket_name" { value = aws_s3_bucket.artifacts.id }
output "artifact_bucket_arn" { value = aws_s3_bucket.artifacts.arn }
output "artifact_kms_key_arn" { value = aws_kms_key.artifacts.arn }
