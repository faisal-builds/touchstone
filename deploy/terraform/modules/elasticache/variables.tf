variable "name" { type = string }
variable "node_type" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "allowed_cidr_blocks" { type = list(string) }
variable "tags" {
  type    = map(string)
  default = {}
}
