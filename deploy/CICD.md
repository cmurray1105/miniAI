# CI/CD

One workflow, `.github/workflows/cicd.yml`, does both:

| Stage | Where | What |
|---|---|---|
| CI | GitHub-hosted runners | ruff + pytest, dataset-generator smoke test, `terraform fmt`/`validate` (no AWS creds — `-backend=false`), `ansible-playbook --syntax-check` |
| CD | Self-hosted runner **on the Mac mini** | `git merge --ff-only origin/main` into the standing checkout, then re-run the idempotent Ansible playbook, then hit `/healthz` |

Deploy is just "converge the host to what main says" — the same
`ansible-playbook ansible/site.yml` you'd run by hand. There is no separate
deploy script to drift out of sync.

## One-time runner setup (on the mini)

1. GitHub repo → Settings → Actions → Runners → **New self-hosted runner**
   → macOS / ARM64. Follow the download/config commands it prints. When
   `config.sh` asks for labels, add `miniai`.

2. Install it as a service so it survives reboots:

```
cd ~/actions-runner
./svc.sh install
./svc.sh start
```

3. Repo → Settings → Secrets and variables → Actions → **Variables**:
   - `DEPLOY_ENABLED` = `true`  (delete or set to anything else to pause CD)
   - `MINIAI_DIR` = `/Users/cmurray/LinkedIn/miniAI`  (optional; this is the default)

## Security notes (interview-grade honesty)

- **Self-hosted runners + public repos are a real risk**: anyone who can get
  a workflow to run gets code execution on the host. Mitigations in place:
  - Settings → Actions → General → Fork pull request workflows: **require
    approval for all outside collaborators** (set this!).
  - The deploy job only triggers on `push` to `main` — never on `pull_request`
    — so fork PRs can't reach the mini even if CI runs.
  - The runner runs as the unprivileged `cmurray` user; provisioning needs no
    sudo (launchd user agents, brew services).
- `--ff-only` on the deploy pull: history rewrites on main fail the deploy
  instead of silently rewriting the host's checkout.
- `concurrency: deploy-mini` serializes deploys; a push during a provision
  queues rather than racing it.
- CI needs zero AWS credentials. Terraform changes are validated in CI but
  **applied by a human** (`make infra-apply`) — state-touching operations
  stay deliberate.

## Rollback

```
git -C ~/LinkedIn/miniAI revert <bad-commit> && git push   # or revert in GitHub UI
```

The next deploy converges the host back. For an emergency stop with a broken
runner: set `DEPLOY_ENABLED` to `false` and fix by hand.
