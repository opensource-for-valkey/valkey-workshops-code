.PHONY: setup start run test inspect stop

setup:
	uv sync --dev

start:
	docker compose up -d --wait

run:
	uv run uvicorn semantic_cache.api:app --reload --host 127.0.0.1 --port 8000

test:
	uv run pytest -q

inspect:
	valkey-cli -p 16379 --scan --pattern 'semantic-faq-cache:v1:*'
	valkey-cli -p 16379 FT.INFO semantic_faq_cache_v1

stop:
	docker compose down
