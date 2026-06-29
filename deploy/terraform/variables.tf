variable "region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region for all resources."
}

variable "environment" {
  type        = string
  default     = "production"
  description = "Environment name (production, staging)."
}

variable "vpc_cidr" {
  type        = string
  default     = "10.40.0.0/16"
  description = "CIDR block for the VPC."
}

variable "availability_zone_count" {
  type        = number
  default     = 3
  description = "Number of AZs to spread subnets across (multi-AZ HA)."
}

variable "cluster_version" {
  type        = string
  default     = "1.30"
  description = "EKS Kubernetes version."
}

variable "postgres_version" {
  type        = string
  default     = "16.3"
  description = "RDS PostgreSQL engine version."
}

variable "postgres_instance_class" {
  type        = string
  default     = "db.r6g.large"
  description = "RDS instance class."
}

variable "postgres_allocated_storage" {
  type        = number
  default     = 100
  description = "RDS allocated storage (GiB)."
}

variable "redis_node_type" {
  type        = string
  default     = "cache.r6g.large"
  description = "ElastiCache Redis node type."
}

variable "domain_name" {
  type        = string
  default     = "touchstone.example.com"
  description = "Apex domain; ACM cert covers app/api/robustness subdomains."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Additional tags merged into all resources."
}
