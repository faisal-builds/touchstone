variable "name" { type = string }
variable "vpc_cidr" { type = string }
variable "availability_zone_count" {
  type    = number
  default = 3
}
variable "tags" {
  type    = map(string)
  default = {}
}
