output "host_access_key_id" {
  value = aws_iam_access_key.miniai_host.id
}

output "host_secret_access_key" {
  value     = aws_iam_access_key.miniai_host.secret
  sensitive = true # print once with: terraform output -raw host_secret_access_key
}

output "demo_token" {
  value     = aws_ssm_parameter.demo_token.value
  sensitive = true
}

output "config_parameter_path" {
  value = "/miniai/config/"
}

output "route53_zone_name_servers" {
  value = var.domain_name != "" ? data.aws_route53_zone.main[0].name_servers : []
}

output "github_packer_role_arn" {
  description = "Set this as the AWS_PACKER_ROLE_ARN GitHub Environment variable for infrastructure"
  value       = aws_iam_role.github_packer.arn
}
