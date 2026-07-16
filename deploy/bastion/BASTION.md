# AWS edge: EC2 bastion + WireGuard (the deployed path)

```
recruiter ─▶ Route 53 (hosted zone, $0.50/mo)
           ─▶ EC2 t4g.nano + Elastic IP (~$7.30/mo)
              nginx: TLS (Let's Encrypt), rate limiting, reverse proxy
           ─▶ WireGuard (UDP 51820) ◀── OUTBOUND connection from the Mac mini
           ─▶ mini gateway 10.8.0.2:8000 / grafana 10.8.0.2:3000
```

The mini keeps **zero inbound ports** — its WireGuard client dials out to the
bastion and keeps the tunnel alive (`PersistentKeepalive`). All public attack
surface lives on a disposable ~$7/mo box. The image is built by Packer and
Terraform attaches the durable Elastic IP, so a replacement retains DNS.

## Immutable-image path

This is deliberately **EC2, not ECS**. One ARM instance with a fixed network
identity, nginx, WireGuard, and a local trace store does not gain meaningful
availability from an ECS control plane; it does gain cost and deployment
surface. Packer bakes the repeatable OS layer (packages, forwarding, unattended
updates) into an ARM64 AMI. Terraform remains the owner of the instance,
security group, and EIP.

GitHub Actions builds the image automatically when `packer/`,
`deploy/bastion/`, or its AMI workflow changes on `main`; **Build bastion AMI**
also supports a deliberate manual rebuild. Terraform creates the narrowly
scoped OIDC role. Apply it once, then set its output as the non-secret
`AWS_PACKER_ROLE_ARN` variable in GitHub's `infrastructure` environment (the
role ARN is an identifier, not a credential):

```bash
terraform output -raw github_packer_role_arn
```

No AWS access key is stored in GitHub. The job produces an AMI named
`miniai-bastion-*`. After the first successful build,
set this in the Terraform invocation or tfvars:

```hcl
use_packer_bastion_ami = true
```

Terraform then selects the newest self-owned `miniai-bastion-*` ARM64 AMI.
Packer never bakes WireGuard private keys, TLS certificates, DNS hostnames, or
nginx vhosts: those are runtime configuration and copying them into an image
would duplicate secrets. On first boot, cloud-init fetches the runtime config
from SSM, configures WireGuard/nginx/Tempo, waits for Route 53 to resolve to
the attached EIP, and obtains the Let's Encrypt certificate automatically.

Before the first replacement, migrate the identity from the live bastion. This
is a one-time operation and does not print the private key:

```bash
./deploy/bastion/migrate-runtime-identity.sh
```

If your EC2 key is not your default SSH identity, specify it without exposing
the key material:

```bash
SSH_IDENTITY_FILE=~/.ssh/id_ed25519 ./deploy/bastion/migrate-runtime-identity.sh
```

If the legacy certificate has no recorded contact email, supply the address to
receive Let's Encrypt expiration notices:

```bash
ACME_EMAIL=you@example.com SSH_IDENTITY_FILE=~/.ssh/id_ed25519 \
  ./deploy/bastion/migrate-runtime-identity.sh
```

Then `terraform apply` can replace the instance. The EIP remains stable and
the existing Mini WireGuard peer continues to work because its server identity
is preserved in SSM.

## Access: Systems Manager, not more SSH

The Ubuntu source AMI already includes the SSM Agent. Terraform attaches an
EC2 instance profile with AWS's `AmazonSSMManagedInstanceCore` policy, so the
agent can register after launch. No separate agent install is required. Once
the host appears in Systems Manager, use Session Manager for audited shell
access; SSH remains available only as the bootstrap break-glass path and can
later be removed from the security group.

## One-time setup

### 1. Provision (from terraform/)

```bash
terraform apply -var "ssh_public_key=$(cat ~/.ssh/id_ed25519.pub)"
terraform output bastion_public_ip
```

The `ssh_public_key` var becomes an EC2 key pair, so the bastion trusts the
key you already have — no console key downloads:

```bash
ssh ubuntu@$(terraform output -raw bastion_public_ip)
```

### 2. WireGuard keys (generate where each key lives; private keys never move)

```bash
# on the mini
brew install wireguard-tools
wg genkey | tee ~/.wg-mini.key | wg pubkey        # note MINI_PUBKEY

# on the bastion (ssh ubuntu@<bastion_ip>)
wg genkey | sudo tee /etc/wireguard/server.key | wg pubkey   # note BASTION_PUBKEY
sudo chmod 600 /etc/wireguard/server.key
```

### 3. Bastion WireGuard — /etc/wireguard/wg0.conf (from wg0-bastion.conf)

Fill in the keys, then:

```bash
sudo systemctl enable --now wg-quick@wg0
```

### 4. Mini WireGuard — ~/wg0.conf (from wg0-mini.conf)

```bash
sudo wg-quick up ~/wg0.conf
ping 10.8.0.1        # bastion answers over the tunnel
```

To survive reboots, install as a LaunchDaemon (root — wg needs it):
`sudo cp deploy/bastion/com.miniai.wireguard.plist /Library/LaunchDaemons/ && sudo launchctl bootstrap system /Library/LaunchDaemons/com.miniai.wireguard.plist`

### 5. nginx + TLS on the bastion

```bash
sudo cp nginx-miniai.conf /etc/nginx/sites-available/miniai
sudo ln -s /etc/nginx/sites-available/miniai /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d mini-agent.dev -d grafana.mini-agent.dev
```

Grafana is served from a dedicated subdomain, not a URL subpath. Before
visiting it externally, apply the host configuration so Grafana knows its
canonical HTTPS URL and restarts with the reverse-proxy settings:

```bash
ansible-playbook ansible/site.yml
```

Then open `https://grafana.mini-agent.dev/`. If Grafana has already been
provisioned, rerunning the playbook is safe and only restarts Grafana when its
configuration changes.

Grafana uses a separate nginx rate-limit zone from the model gateway. A
browser dashboard load requests many JavaScript and CSS chunks concurrently;
applying the gateway's 30 requests/minute limit to those assets causes nginx
to return 503 and Grafana to report a missing chunk.

certbot auto-renews via systemd timer. `.dev` is HSTS-preloaded, so the
https-only redirect nginx sets up isn't optional — it's load-bearing.

### 6. Verify the layers independently

```bash
curl -s http://10.8.0.2:8000/healthz     # from bastion: tunnel + gateway
curl -s https://mini-agent.dev/healthz   # from anywhere: full path
```

## Honest trade-offs vs the Cloudflare alternative

You own TLS renewal, nginx patching, and the bastion OS (unattended-upgrades
is enabled in the bootstrap). DDoS absorption is one nano instance, not a
global anycast edge — the gateway's rate limiting and load shedding are doing
real work here. In exchange: every hop is AWS, every hop is yours, and the
whole edge is reproducible from `terraform apply`. For a DevOps portfolio,
that's the point.
