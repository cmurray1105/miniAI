packer {
  required_plugins {
    amazon = {
      version = ">= 1.3.0"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "ami_name_prefix" {
  type    = string
  default = "miniai-bastion"
}

source "amazon-ebs" "bastion" {
  region        = var.aws_region
  instance_type = "t4g.small"
  ssh_username  = "ubuntu"
  ami_name      = "${var.ami_name_prefix}-{{timestamp}}"

  source_ami_filter {
    filters = {
      architecture        = "arm64"
      name                = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["099720109477"] # Canonical
  }

  tags = {
    Name      = "${var.ami_name_prefix}-{{timestamp}}"
    Project   = "miniAI"
    ManagedBy = "packer"
    Role      = "edge-bastion"
  }
}

build {
  name    = "miniai-edge-bastion"
  sources = ["source.amazon-ebs.bastion"]

  provisioner "shell" {
    script = "${path.root}/scripts/bootstrap-bastion.sh"
  }
}
