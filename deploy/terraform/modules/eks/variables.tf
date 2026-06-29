variable "name" { type = string }
variable "cluster_version" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "tags" {
  type    = map(string)
  default = {}
}
