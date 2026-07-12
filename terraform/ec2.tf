# Edge bastion: EC2 t4g.nano running nginx (TLS termination) + WireGuard.
# The Mac mini connects OUTBOUND to this box; nothing at home is exposed.
#
# Cost math (us-east-1): instance ~$3.07/mo + public IPv4 ~$3.60/mo + 8GB
# gp3 ~$0.64/mo ≈ $7.30/mo. A Lightsail nano bundles the same for $5 flat —
# EC2 was chosen anyway for the standard building blocks (SG, EIP, key
# pair, AMI lookup) that make this a portfolio-grade edge, not a toy.
#
# Uses the account's default VPC: a single public nginx box needs no subnet
# design, and the default VPC's public subnets + IGW are exactly that.

variable "bastion_instance_type" {
  description = "Bastion instance type (arm64)"
  type        = string
  default     = "t4g.nano"
}

variable "ssh_allowed_cidrs" {
  description = "CIDRs allowed to SSH to the bastion (tighten to your IP!)"
  type        = list(string)
  default     = ["0.0.0.0/0"] # CHANGE ME: e.g. ["203.0.113.7/32"]
}

variable "ssh_public_key" {
  description = "SSH public key line for bastion access (e.g. contents of ~/.ssh/id_ed25519.pub)"
  type        = string
  default     = ""
}

# Canonical publishes the current Ubuntu AMI id to public SSM parameters —
# no hardcoded, region-specific, silently-aging AMI ids.
data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_key_pair" "bastion" {
  count      = var.domain_name != "" && var.ssh_public_key != "" ? 1 : 0
  key_name   = "miniai-bastion"
  public_key = var.ssh_public_key
}

resource "aws_security_group" "bastion" {
  count       = var.domain_name != "" ? 1 : 0
  name        = "miniai-bastion"
  description = "miniAI edge: https + wireguard in, ssh restricted"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "http (certbot http-01 challenge + redirect to https)"
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "https"
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "wireguard from the mini"
    protocol    = "udp"
    from_port   = 51820
    to_port     = 51820
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "ssh"
    protocol    = "tcp"
    from_port   = 22
    to_port     = 22
    cidr_blocks = var.ssh_allowed_cidrs
  }
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "miniai-bastion" }
}

resource "aws_instance" "bastion" {
  count = var.domain_name != "" ? 1 : 0

  ami                    = data.aws_ssm_parameter.ubuntu_ami.value
  instance_type          = var.bastion_instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.bastion[0].id]
  key_name               = var.ssh_public_key != "" ? aws_key_pair.bastion[0].key_name : null

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  # Bootstrap: packages only. WireGuard keys and TLS certs are interactive
  # one-time steps documented in deploy/bastion/BASTION.md — private keys
  # do not belong in Terraform state or user_data.
  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y nginx wireguard certbot python3-certbot-nginx
    sysctl -w net.ipv4.ip_forward=1
    echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-wireguard.conf
  EOT

  tags = { Name = "miniai-bastion" }
}

# Elastic IP: free while attached to a running instance; the IPv4 itself is
# the ~$3.60/mo line item. DNS records reference this, so instance rebuilds
# keep the same address.
resource "aws_eip" "bastion" {
  count  = var.domain_name != "" ? 1 : 0
  domain = "vpc"
  tags   = { Name = "miniai-bastion" }
}

resource "aws_eip_association" "bastion" {
  count         = var.domain_name != "" ? 1 : 0
  instance_id   = aws_instance.bastion[0].id
  allocation_id = aws_eip.bastion[0].id
}

output "bastion_public_ip" {
  value = var.domain_name != "" ? aws_eip.bastion[0].public_ip : null
}
