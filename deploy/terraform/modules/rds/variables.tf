variable "name" { type = string }
variable "engine_version" { type = string }
variable "instance_class" { type = string }
variable "allocated_storage" { type = number }
variable "vpc_id" { type = string }
variable "database_subnet_ids" { type = list(string) }
variable "allowed_cidr_blocks" { type = list(string) }
variable "database_name" {
  type    = string
  default = "touchstone"
}
variable "master_username" {
  type    = string
  default = "touchstone"
}
variable "tags" {
  type    = map(string)
  default = {}
}
