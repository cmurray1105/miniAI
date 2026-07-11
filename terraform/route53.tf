# Optional DNS layer. Set domain_name to enable; leave "" to skip.
#
# Honest architecture note: Cloudflare Tunnel requires its hostname's zone to
# be served by Cloudflare nameservers (free tier doesn't do partial/subdomain
# zones). So the working pattern with a Route 53-registered domain is:
#   Route 53 = registrar + this hosted zone as source of truth,
#   with NS delegation pointing the zone at Cloudflare (var below).
# If you skip Cloudflare and use the Lightsail bastion (deploy/EDGE.md
# option B), point the A record at the bastion's static IP instead.

variable "cloudflare_name_servers" {
  description = "Cloudflare-assigned NS for the zone (from the Cloudflare dashboard); empty list = no delegation"
  type        = list(string)
  default     = []
}

resource "aws_route53_zone" "main" {
  count = var.domain_name != "" ? 1 : 0
  name  = var.domain_name
}

resource "aws_route53_record" "cloudflare_delegation" {
  count = var.domain_name != "" && length(var.cloudflare_name_servers) > 0 ? 1 : 0

  zone_id = aws_route53_zone.main[0].zone_id
  name    = var.domain_name
  type    = "NS"
  ttl     = 172800
  records = var.cloudflare_name_servers
}
