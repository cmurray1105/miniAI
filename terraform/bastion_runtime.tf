# Runtime configuration is delivered at first boot from Parameter Store. The
# WireGuard private key and ACME email are migrated separately because they
# already exist on the live bastion; they are never committed or baked.

locals {
  bastion_runtime_parameters = {
    "nginx-config" = file("${path.module}/../deploy/bastion/nginx-miniai.conf")
    "tempo-config" = file("${path.module}/../deploy/bastion/tempo.yaml")
  }
}

resource "aws_ssm_parameter" "bastion_runtime" {
  for_each = var.domain_name != "" ? local.bastion_runtime_parameters : {}

  name  = "/miniai/bastion/${each.key}"
  type  = "String"
  value = each.value
}
