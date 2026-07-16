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
surface lives on a disposable ~$7/mo box that can be rebuilt by Terraform in
two minutes (the Elastic IP survives rebuilds, so DNS never moves).

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
