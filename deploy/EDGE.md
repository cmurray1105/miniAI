# Public ingress: getting recruiter traffic to a Mac mini safely

Design goal: **zero open inbound ports** on the home network, TLS everywhere,
DDoS absorption at the edge, and a monthly bill measured in cents. Below are
the two options I evaluated, the way you'd write it up in a design doc.

## Option A (deployed): Route 53 + Cloudflare Tunnel — ~$0.50/mo

```
recruiter → miniai.yourdomain.com
          → Route 53 (DNS, $0.50/mo hosted zone)
          → Cloudflare edge (TLS termination, WAF, DDoS absorption, free tier)
          → cloudflared tunnel (OUTBOUND-only connection from the mini)
          → gateway :8000 (auth, rate limit, queue)  →  mlx_lm.server :8080
```

Why it wins:
- The mini makes an *outbound* connection to Cloudflare; nothing on the home
  router is exposed. No port forwarding, no dynamic-DNS hacks, no attack surface.
- Free TLS, HTTP/2, caching of static assets, and IP-level rate limiting at
  the edge — before traffic ever reaches the house.
- Route 53 stays the DNS source of truth (NS-delegated subdomain or full zone),
  which keeps the AWS skills visible and makes it trivial to swap edges later.

Setup:
```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create miniai
cloudflared tunnel route dns miniai miniai.yourdomain.com
cloudflared tunnel run --config deploy/cloudflared.yml miniai
```

## Option B (evaluated, documented): all-AWS with a Lightsail bastion — ~$5/mo

```
recruiter → Route 53 → Lightsail nano ($3.50/mo, static IP)
          → nginx (TLS via ACM/certbot, rate limiting)
          → WireGuard tunnel → Mac mini gateway :8000
```

- The mini keeps zero inbound ports (WireGuard peers outbound to the bastion).
- More moving parts you own: nginx config, WireGuard keys, patching the bastion.
- Choose this if the goal is to demonstrate hands-on EC2/nginx/WireGuard work;
  the config lives in `deploy/bastion/` as a documented alternative.

## What I deliberately did NOT use

- **ALB/NLB (~$16+/mo):** load-balancing a single origin is resume theater.
  The write-up says so; interviewers respect the cost reasoning more than the logo.
- **API Gateway + VPN:** per-request pricing plus a managed VPN attachment is
  wildly over-spec for one host. Same skills are demonstrated by the gateway code.

## Defense in depth (either option)

1. Edge: TLS, DDoS absorption, coarse IP rate limits
2. Tunnel: outbound-only, authenticated, encrypted
3. Gateway: bearer-token auth (optional), 6 req/min/IP, bounded queue (503s > OOM)
4. Agent: read-only allowlisted tools, no shell, hard cap on tool-call loops
5. Host: gateway and model server bind 127.0.0.1 only; macOS firewall on
