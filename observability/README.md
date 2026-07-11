# Observability: native by default, Docker as the portable alternative

## The sizing decision (this is the kind of thing the demo exists to show)

The observability workload is trivial — Prometheus scraping one target at
15s intervals (~50-150 MB), Grafana idle (~200 MB). But macOS runs Linux
containers inside a VM that wires **2-8 GB** regardless of what the
containers actually use.

On a 16 GB Apple Silicon host that matters more than it would anywhere else:
unified memory means there is no separate VRAM — Metal's usable working set
(~10-12 GB on this box) and the Docker VM come out of the same pool. The
budget during a training run:

| consumer                        | approx    |
|---------------------------------|-----------|
| macOS baseline                  | ~3 GB     |
| QLoRA training peak             | ~7-9 GB   |
| observability, native           | ~0.3 GB   |
| observability, Docker VM        | ~2-4 GB   |

Native fits with headroom. Docker pushes the box into swap exactly when the
GPU is busiest. So the default is Homebrew + `brew services` (launchd under
the hood — consistent with how everything else on this host is supervised):

```bash
brew install prometheus grafana
make provision        # ansible installs configs and starts both
# or manually: brew services start prometheus && brew services start grafana
```

`ansible/site.yml` places `native/prometheus.yml` at
`$(brew --prefix)/etc/prometheus.yml` and the Grafana provisioning files
under `$(brew --prefix)/etc/grafana/provisioning/`.

## Docker variant (kept for portability)

`docker-compose.yml` still works and is the right choice on a Linux host or
a Mac with RAM to spare — containers there cost what they use. It is not the
default on this 16 GB mini for the reasons above.
