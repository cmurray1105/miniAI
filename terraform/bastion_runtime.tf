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

  # Created parameters inherit the provider default tags. The ACME value is
  # imported after a one-time migration, and AWS provider default-tag handling
  # can otherwise present a perpetual cosmetic diff on imported SSM params.
  lifecycle {
    ignore_changes = [tags, tags_all]
  }
}

# The initial value was populated by the one-time runtime-identity migration.
# Import it into Terraform state so all future values are managed declaratively.
import {
  to = aws_ssm_parameter.bastion_runtime["acme-email"]
  id = "/miniai/bastion/acme-email"
}
