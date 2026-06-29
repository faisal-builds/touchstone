variable "name" { type = string }
variable "oidc_provider_arn" { type = string }
variable "oidc_provider_url" { type = string }
variable "artifact_bucket_arn" { type = string }
variable "secrets_manager_arn" { type = string }
variable "app_namespace" {
  type    = string
  default = "touchstone"
}
variable "app_service_account" {
  type    = string
  default = "touchstone"
}
variable "external_secrets_namespace" {
  type    = string
  default = "external-secrets"
}
variable "external_secrets_service_account" {
  type    = string
  default = "external-secrets"
}
variable "tags" {
  type    = map(string)
  default = {}
}
