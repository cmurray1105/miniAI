# DNS: Route 53 hosted zone as the source of truth, records pointing at the
# EC2 bastion's Elastic IP. Set domain_name to enable.
#
# The zone from domain registration is looked up, not created — if you deleted
# it, recreate it first (Route 53 -> Hosted zones -> Create), then update the
# nameservers under Registered domains to the new zone's NS values (every
# fresh zone is assigned a different NS set).

data "aws_route53_zone" "main" {
  count = var.domain_name != "" ? 1 : 0
  name  = var.domain_name
}

resource "aws_route53_record" "apex" {
  count = var.domain_name != "" ? 1 : 0

  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = var.domain_name
  type    = "A"
  ttl     = 300
  records = [aws_eip.bastion[0].public_ip]
}

resource "aws_route53_record" "grafana" {
  count = var.domain_name != "" ? 1 : 0

  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "grafana.${var.domain_name}"
  type    = "A"
  ttl     = 300
  records = [aws_eip.bastion[0].public_ip]
}
