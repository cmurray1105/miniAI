# miniAI — every workflow is one make target away.

.PHONY: setup dataset train eval-base eval-tuned eval-report serve-model \
        serve-model-tuned serve-gateway obs-up obs-down obs-docker-up \
        infra-plan infra-apply provision tunnel tunnel-cf test lint chat

setup:            ## install runtime deps (on the Mac mini)
	pip install -r requirements.txt

dataset:          ## regenerate train/valid/test + eval cases (deterministic)
	python data/generate_dataset.py --out data

train:            ## QLoRA fine-tune (~1-2h on 16GB M-series)
	mlx_lm.lora --config training/lora_config.yaml

serve-model:      ## model server, BASE model (for baseline eval)
	mlx_lm.server --model mlx-community/Qwen3.5-9B-MLX-4bit --port 8080

serve-model-tuned:## model server with the fine-tuned adapter
	mlx_lm.server --model mlx-community/Qwen3.5-9B-MLX-4bit \
		--adapter-path adapters/incident-copilot-v1 --port 8080

eval-base:        ## behavioral eval against whatever is on :8080
	python eval/run_eval.py --label base

eval-tuned:
	python eval/run_eval.py --label tuned

eval-report:      ## side-by-side: what did the fine-tune buy us?
	python eval/run_eval.py --compare eval/results-base.json eval/results-tuned.json

serve-gateway:    ## gateway on :8000 (launchd normally owns this; manual run for dev)
	uvicorn server.gateway:app --host 0.0.0.0 --port 8000

chat:             ## local REPL against the agent
	python -m agent.agent

obs-up:           ## Prometheus + Grafana, native (~300 MB; see observability/README.md)
	brew services start prometheus && brew services start grafana

obs-down:
	brew services stop prometheus && brew services stop grafana

obs-docker-up:    ## Docker alternative — costs a 2-8 GB VM on macOS; avoid on 16 GB
	docker compose -f observability/docker-compose.yml up -d

infra-plan:       ## preview AWS changes (SSM config, IAM, bastion, DNS)
	cd terraform && terraform init && terraform plan

infra-apply:      ## apply the AWS layer
	cd terraform && terraform apply

provision:        ## idempotent host setup (deps, launchd services, observability)
	ansible-playbook ansible/site.yml

tunnel:           ## WireGuard up to the AWS bastion (see deploy/bastion/BASTION.md)
	sudo wg-quick up /etc/wireguard/wg0.conf

tunnel-cf:        ## Cloudflare alternative (see deploy/EDGE.md option B)
	cloudflared tunnel run --config deploy/cloudflared.yml miniai

test:
	pytest -q

lint:
	ruff check .
