# Runtime configuration is delivered at first boot from Parameter Store. The
# WireGuard private key and ACME email are migrated separately because they
# already exist on the live bastion; they are never committed or baked.

locals {
  bastion_runtime_parameters = {
    "nginx-config" = file("${path.module}/../deploy/bastion/nginx-miniai.conf")
    "tempo-config" = file("${path.module}/../deploy/bastion/tempo.yaml")
    "acme-email"   = var.acme_email
  }
}

resource "aws_ssm_parameter" "bastion_runtime" {
  for_each = var.domain_name != "" ? local.bastion_runtime_parameters : {}

  name  = "/miniai/bastion/${each.key}"
  type  = "String"
  value = each.value

  # Explicit as well as provider-default tags: this parameter was initially
  # created by the one-time migration script and is imported into state later.
  # Explicit tags prevent import reconciliation from stripping provenance.
  tags = {
    ManagedBy = "terraform"
    Project   = "miniAI"
  }
}

# The initial value was populated by the one-time runtime-identity migration.
# Import it into Terraform state so all future values are managed declaratively.
import {
  to = aws_ssm_parameter.bastion_runtime["acme-email"]
  id = "/miniai/bastion/acme-email"
}
