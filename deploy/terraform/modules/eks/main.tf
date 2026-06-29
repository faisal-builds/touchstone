# --- Cluster IAM role -------------------------------------------------------
data "aws_iam_policy_document" "cluster_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${var.name}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.cluster_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# --- Control plane ----------------------------------------------------------
resource "aws_eks_cluster" "this" {
  name     = var.name
  version  = var.cluster_version
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = true
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  depends_on = [aws_iam_role_policy_attachment.cluster]
  tags       = var.tags
}

# --- IRSA: OIDC provider ----------------------------------------------------
data "tls_certificate" "oidc" {
  url = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "oidc" {
  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.oidc.certificates[0].sha1_fingerprint]
  tags            = var.tags
}

# --- Node IAM role ----------------------------------------------------------
data "aws_iam_policy_document" "node_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${var.name}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
  ])
  role       = aws_iam_role.node.name
  policy_arn = each.value
}

# --- Managed node groups ----------------------------------------------------
# General-purpose group for stateless services + the dashboard.
resource "aws_eks_node_group" "general" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "general"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = ["m6i.large"]

  scaling_config {
    desired_size = 3
    min_size     = 3
    max_size     = 10
  }
  update_config {
    max_unavailable = 1
  }
  labels = { "touchstone.io/pool" = "general" }

  depends_on = [aws_iam_role_policy_attachment.node]
  tags       = var.tags
}

# Sandbox group: runs gVisor (runsc) workloads. Tainted + labelled so only pods
# with runtimeClassName=gvisor (matching toleration/nodeSelector) schedule here.
# The runsc shim is installed via the launch-template bootstrap / a node
# bootstrap DaemonSet (out of scope for this module; see ops guide).
resource "aws_eks_node_group" "sandbox" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "sandbox-gvisor"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = ["m6i.xlarge"]

  scaling_config {
    desired_size = 2
    min_size     = 2
    max_size     = 20
  }
  update_config {
    max_unavailable = 1
  }
  labels = {
    "touchstone.io/pool"    = "sandbox"
    "touchstone.io/sandbox" = "gvisor"
  }
  taint {
    key    = "touchstone.io/sandbox"
    value  = "gvisor"
    effect = "NO_SCHEDULE"
  }

  depends_on = [aws_iam_role_policy_attachment.node]
  tags       = var.tags
}
