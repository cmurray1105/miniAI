# Public ingress: getting recruiter traffic to a Mac mini safely

Design goals: **zero open inbound ports at home**, TLS everywhere (mandatory —
`.dev` is HSTS-preloaded), every layer as code, and a bill a job-seeker can
ignore. Two options were evaluated; the all-AWS path is deployed.

## Option A (deployed): all-AWS — Route 53 + EC2 bastion + WireGuard, ~$7.80/mo

```
recruiter → Route 53 hosted zone ($0.50/mo)
          → EC2 t4g.nano + Elastic IP (~$7.30/mo)
            nginx: Let's Encrypt TLS, edge rate limiting, reverse proxy
          → WireGuard (UDP 51820) ◀── OUTBOUND-only connection from the mini
          → gateway 10.8.0.2:8000 → mlx_lm.server :8080
```

- The mini's WireGuard client dials **out** to the bastion and holds the
  tunnel open (`PersistentKeepalive`) — the home network exposes nothing.
- All public attack surface lives on a $5 box that Terraform can rebuild in
  two minutes (`terraform/ec2.tf`: instance, EIP, security group,
  DNS records — the whole edge is code).
- Owned trade-offs, stated plainly: TLS renewal (certbot systemd timer),
  nginx and OS patching, and DDoS absorption that is one nano instance rather
  than a global anycast network. The gateway's own rate limiting and load
  shedding carry real weight in this design.

Setup runbook: `deploy/bastion/BASTION.md`.

## Option B (evaluated, documented): Cloudflare Tunnel — $0/mo

```
recruiter → Cloudflare edge (TLS, WAF, DDoS absorption, free tier)
          → cloudflared (outbound-only from the mini) → gateway :8000
```

Cheaper and less to maintain — Cloudflare terminates TLS and absorbs DDoS for
free, and there is no bastion to patch. The costs are architectural: DNS must
be served by Cloudflare nameservers (Route 53 demoted to registrar), a
closed-source daemon runs on the mini, and a third party sits in the TLS
path. Config kept in `deploy/cloudflared.yml`; swapping edges is a one-hour
change precisely because the gateway never knows which edge is in front of it.

## Why not the "obvious" AWS answers

- **ALB/NLB (~$16+/mo):** load-balancing a single origin is resume theater —
  and it still can't reach a home network without a tunnel or VPN attachment.
- **API Gateway + Site-to-Site VPN:** per-request pricing plus ~$36/mo for the
  VPN attachment, to serve one host. The same skills show up in the gateway
  code for free.

## Defense in depth (as deployed)

1. Edge (bastion): TLS, HSTS, nginx rate limiting (30 req/min/IP, burst 10)
2. Tunnel: WireGuard — outbound-only from home, modern crypto, 25s keepalive
3. Gateway: optional bearer auth, 6 req/min/IP, bounded queue (503s > OOM)
4. Agent: read-only allowlisted tools, no shell, hard cap on tool-call loops
5. Host: gateway and model server bind localhost + WireGuard interface only;
   macOS firewall on; AWS credential scoped to one SSM parameter path
