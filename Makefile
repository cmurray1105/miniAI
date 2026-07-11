# miniAI — every workflow is one make target away.

.PHONY: setup dataset train eval-base eval-tuned eval-report serve-model \
        serve-model-tuned serve-gateway obs-up obs-down tunnel test lint chat

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

serve-gateway:    ## public-facing gateway on :8000
	uvicorn server.gateway:app --host 127.0.0.1 --port 8000

chat:             ## local REPL against the agent
	python -m agent.agent

obs-up:           ## Prometheus + Grafana, native (~300 MB; see observability/README.md)
	brew services start prometheus && brew services start grafana

obs-down:
	brew services stop prometheus && brew services stop grafana

obs-docker-up:    ## Docker alternative — costs a 2-8 GB VM on macOS; avoid on 16 GB
	docker compose -f observability/docker-compose.yml up -d

tunnel:           ## public ingress (see deploy/EDGE.md)
	cloudflared tunnel run --config deploy/cloudflared.yml miniai

test:
	pytest -q

lint:
	ruff check .
