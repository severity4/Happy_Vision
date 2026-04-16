.PHONY: dev build serve lint test verify help install app

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

dev: ## Dev mode (Flask 8081 + Vite 5176)
	@echo "Starting Flask (8081) + Vite (5176)..."
	@python3 web_ui.py &
	@cd frontend && npm run dev

serve: ## Production mode (Flask only, serves Vue build)
	python3 web_ui.py

build: ## Build Vue frontend
	cd frontend && npm run build

lint: ## Lint Python
	ruff check modules api tests web_ui.py cli.py

test: ## Run pytest
	pytest -q

verify: ## Pre-merge verification
	ruff check modules api tests web_ui.py cli.py
	pytest -q

install: ## Install all dependencies
	pip install -r requirements.txt
	@if [ -d frontend ]; then cd frontend && npm install; fi

app: ## Build macOS .app
	python3 build_app.py
