# Edge bastion: Lightsail nano running nginx (TLS termination) + WireGuard.
# The Mac mini connects OUTBOUND to this box; nothing at home is exposed.
#
# Bundle/blueprint IDs drift over time — verify with:
#   aws lightsail get-bundles --query 'bundles[?supportedPlatforms[0]==`LINUX_UNIX`].[bundleId,price]'
#   aws lightsail get-blueprints --query 'blueprints[?platform==`LINUX_UNIX`].[blueprintId]'

variable "bastion_bundle_id" {
  description = "Lightsail bundle (nano, ~$5/mo with IPv4)"
  type        = string
  default     = "nano_3_0"
}

variable "bastion_blueprint_id" {
  description = "Lightsail OS image"
  type        = string
  default     = "ubuntu_24_04"
}

variable "ssh_allowed_cidrs" {
  description = "CIDRs allowed to SSH to the bastion (tighten to your IP!)"
  type        = list(string)
  default     = ["0.0.0.0/0"] # CHANGE ME: e.g. ["203.0.113.7/32"]
}

resource "aws_lightsail_instance" "bastion" {
  count = var.domain_name != "" ? 1 : 0

  name              = "miniai-bastion"
  availability_zone = "${var.aws_region}a"
  blueprint_id      = var.bastion_blueprint_id
  bundle_id         = var.bastion_bundle_id

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
}

resource "aws_lightsail_static_ip" "bastion" {
  count = var.domain_name != "" ? 1 : 0
  name  = "miniai-bastion-ip"
}

resource "aws_lightsail_static_ip_attachment" "bastion" {
  count          = var.domain_name != "" ? 1 : 0
  static_ip_name = aws_lightsail_static_ip.bastion[0].name
  instance_name  = aws_lightsail_instance.bastion[0].name
}

resource "aws_lightsail_instance_public_ports" "bastion" {
  count         = var.domain_name != "" ? 1 : 0
  instance_name = aws_lightsail_instance.bastion[0].name

  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80 # certbot http-01 challenge + redirect to https
  }
  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
  }
  port_info {
    protocol  = "udp"
    from_port = 51820
    to_port   = 51820 # WireGuard from the mini
  }
  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.ssh_allowed_cidrs
  }
}

output "bastion_public_ip" {
  value = var.domain_name != "" ? aws_lightsail_static_ip.bastion[0].ip_address : null
}
