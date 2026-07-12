# miniAI

**A production-grade LLM platform on a $599 Mac mini.** QLoRA fine-tune of
Qwen3.5-9B into an SRE incident copilot, served publicly behind a real
gateway — auth, rate limiting, load shedding, Prometheus/Grafana, supervised
services, CI, and zero open inbound ports. Total cloud compute cost: **$0**.
Total recurring bill: **~$7.80/month** (EC2 t4g.nano edge bastion + EIP + Route 53
hosted zone) plus ~$12/yr for the domain. Every AWS resource is Terraform-managed.

This is not an "AI is magic" demo. It's the full lifecycle you'd run in
production — train → eval → serve → observe → secure — scaled honestly to
one 16 GB host, with every trade-off written down.

```
                        ┌────────────────────────── Mac mini (16 GB) ──────────────────────────┐
 recruiter ─▶ Route 53 ─▶ EC2 bastion ─▶ WireGuard (outbound-only from mini)            │
              (DNS)       (nginx · TLS ·      │                                                │
                           edge rate limit)   │                                                │
                                             ▼                                                 │
                                        gateway :8000 ────────▶ mlx_lm.server :8080            │
                                        auth · rate limit ·     Qwen3.5-9B-4bit                │
                                        queue · /metrics        + QLoRA adapter                │
                                             │        ▲              │                         │
                                             ▼        │ scrape       ▼                         │
                                        Prometheus :9090 ─▶ Grafana :3000    read-only tools   │
                                                                             (psutil, logs,    │
                                                                              PromQL, probes)  │
                        └──────────────────────────────────────────────────────────────────────┘
```

## What the fine-tune does (and how I know it worked)

The base model is taught a strict operating contract:

1. **Tool discipline** — pick the right read-only diagnostic tool, emit
   schema-valid JSON arguments, never invent data.
2. **Output contract** — every answer in a fixed triage format:
   `Finding / Assessment / Next step`.
3. **Refusal behavior** — write actions (restart, delete, kill) are declined
   with a suggested operator command instead.

"It feels better" is not an eval. `eval/run_eval.py` scores binary behaviors
on 120 held-out cases, base vs. tuned, and prints the delta:

| metric              | what it measures                                   |
|---------------------|----------------------------------------------------|
| tool_selection      | right tool chosen (or correctly no tool)           |
| json_validity       | arguments parse as JSON                            |
| schema_validity     | arguments satisfy the tool's JSON schema           |
| args_exact          | arguments match expected values                    |
| format_adherence    | triage contract followed on no-tool answers        |

The training set (376 examples) is generated deterministically by
`data/generate_dataset.py` — no opaque data blobs; CI regenerates and
validates it on every push.

## Runbook

Prereqs: Apple Silicon Mac, 16 GB+, Python 3.10+, ~6 GB disk for the model.

```bash
# 0. install
make setup

# 1. dataset (deterministic, seeded)
make dataset

# 2. baseline eval — start the BASE model server in one terminal…
make serve-model
# …and in another:
make eval-base            # writes eval/results-base.json

# 3. train (~1-2 h; the model downloads on first run, ~5.5 GB)
make train

# 4. tuned eval — restart the server with the adapter, then re-run
make serve-model-tuned
make eval-tuned
make eval-report          # side-by-side deltas

# 5. serve the demo
make serve-gateway        # gateway + web UI on :8000
make obs-up               # Prometheus :9090, Grafana :3000

# 6. go public (one-time bastion setup: deploy/bastion/BASTION.md)
make tunnel          # WireGuard up to the AWS edge
```

Try it locally at `http://localhost:8000` — the UI shows every tool call the
agent makes, with arguments, results, and latencies. That transparency is the
demo.

## How it's deployed

No orchestrator — deliberately. One host, launchd as the supervisor, and a
deploy script with a health gate:

- **Services:** everything is launchd-supervised — the model server and
  gateway as templated agents (`ansible/templates/`), Prometheus/Grafana
  native via `brew services` (launchd underneath). No Docker on this host:
  the macOS container VM wires 2-8 GB that unified memory can't spare from
  the GPU — the sizing analysis is in `observability/README.md`.
- **Code rollout:** `./deploy/deploy.sh` = pull → pip install → pytest (the
  deploy gate) → `launchctl kickstart` both services → poll `/readyz` for 150 s.
  Fails loud with rollback instructions if the health gate doesn't pass.
- **Model rollout:** adapters are versioned artifacts (`adapters/incident-copilot-v1`).
  A new fine-tune is v2; rollout = point the plist at v2 and kickstart; rollback
  = point back at v1. Adapters are ~20 MB, so keeping every version is free.
- **Infra as code, both layers:** Terraform owns everything cloud-side —
  all SSM config parameters, the SecureString demo token, least-privilege
  IAM, Route 53 (`terraform/`). Ansible owns the host: idempotent provisioning
  of deps, Jinja2-templated launchd services, and the observability stack
  (`ansible/site.yml`). A fresh mini is `terraform apply` + one playbook run.
- **Config & secrets:** ALL runtime config comes from SSM Parameter Store at
  startup — nothing tunable hides in plists or env files. Changing a value is
  a reviewed `terraform apply` + restart. See `deploy/SECRETS.md`.
- **CI:** GitHub Actions lints, runs the platform tests, and regenerates +
  validates the dataset on every push (`.github/workflows/ci.yml`). Training
  itself stays on the mini — MLX needs Apple Silicon.

## Design decisions an interviewer might ask about

**Why QLoRA on-device instead of a cloud GPU?** Cost ($0), privacy, and the
point of the project: mlx-lm trains adapters against the frozen 4-bit base,
so a 9B model fine-tunes in ~7 GB peak — inside a 16 GB mini. Config:
`training/lora_config.yaml` (batch 1 + grad accumulation 4, top-8 layers,
gradient checkpointing, prompt masking).

**Why a gateway instead of exposing the model server?** One model on one box
serves one request at a time. The gateway makes that honest: bounded queue
(depth 8), 503 load shedding instead of OOM, 6 req/min/IP, optional bearer
auth, and Prometheus metrics for all of it. `server/gateway.py` is ~200 lines
and every line is a production concern.

**Why are the agent's tools read-only?** Because it's exposed to the
internet. Allowlisted diagnostics only (metrics, disk, logs, DNS, HTTP
probes, PromQL), no shell, hard cap of 6 tool rounds. The model was also
*trained* to refuse write actions — and the eval measures it.

**Why a ~$7 EC2 nano bastion instead of an ALB?** An ALB in front of a single
origin is resume theater at 3x the price — and it still can't reach a home
network. The bastion (nginx TLS + WireGuard, fully Terraform-managed) keeps
every hop on AWS with zero inbound ports at home. The trade study, including
the Cloudflare Tunnel alternative, is in `deploy/EDGE.md`.

**What breaks first under load?** Queue depth. Watch `gateway_queue_depth`
in Grafana; sustained >4 means past capacity, and the load-shedding 503s are
visible in the requests-by-status panel. SLO: 99% of accepted requests
complete, p95 end-to-end < 30 s at queue ≤ 4.

## Repo map

```
agent/        tools.py (read-only registry) · agent.py (loop) · prompts.py (shared contract)
data/         generate_dataset.py + generated train/valid/test/eval_cases
training/     lora_config.yaml — 16 GB-tuned QLoRA config
eval/         run_eval.py — behavioral base-vs-tuned harness
server/       gateway.py — auth, rate limit, queue, metrics
web/          index.html — chat UI with live tool-call traces
observability/ prometheus + grafana (docker compose, provisioned dashboard)
terraform/    AWS layer: SSM config+secrets, IAM, Route 53 — all as code
ansible/      host provisioning: deps, templated launchd services, observability
deploy/       deploy.sh (health-gated rollout) · cloudflared · EDGE.md · SECRETS.md
tests/        platform tests + dataset invariants (run in CI, no GPU needed)
```

## Stack

MLX / mlx-lm · Qwen3.5-9B (4-bit) · FastAPI · Terraform · Ansible ·
SSM Parameter Store · Prometheus · Grafana · Route 53 · EC2 · nginx ·
WireGuard · launchd · GitHub Actions
