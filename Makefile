.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help install up down restart logs ps build build-runtime migrate shell psql redis-cli fmt lint test reset

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1;38;5;154m%-16s\033[0m %s\n", $$1, $$2}'

install: ## First-time setup (generates .env, builds images, starts the cluster)
	./install.sh

up: ## Start the cluster
	$(COMPOSE) up -d

down: ## Stop the cluster (data volumes are kept)
	$(COMPOSE) down

restart: ## Restart every service
	$(COMPOSE) restart

logs: ## Tail logs (make logs S=api)
	$(COMPOSE) logs -f --tail 200 $(S)

ps: ## Show service status
	$(COMPOSE) ps

build: ## Rebuild the api and web images
	$(COMPOSE) build

build-runtime: ## Rebuild the Python isolate images
	$(COMPOSE) --profile build build runtime-py312 runtime-py311

migrate: ## Apply database migrations
	$(COMPOSE) exec api alembic upgrade head

shell: ## Shell into the control plane
	$(COMPOSE) exec api sh

psql: ## Open psql against the control-plane database
	$(COMPOSE) exec postgres psql -U cubicle -d cubicle

redis-cli: ## Open redis-cli against the control-plane cache
	$(COMPOSE) exec redis redis-cli

fmt: ## Format the API and the console
	$(COMPOSE) run --rm --no-deps api ruff format .
	cd services/web && npm run format

lint: ## Lint the API and the console
	$(COMPOSE) run --rm --no-deps api ruff check .
	cd services/web && npm run lint && npm run typecheck

test: ## Run the API test suite against the working tree (no rebuild needed)
	$(COMPOSE) run --rm --no-deps -e CUBICLE_TESTING=1 \
		-v "$(CURDIR)/services/api:/app" --entrypoint sh api -c \
		'pip install -q "pytest==8.3.4" "pytest-asyncio==0.25.0" && pytest -q --no-header'

clean-isolates: ## Reclaim function isolates left running by a stopped control plane
	@ids=$$(docker ps -aq --filter label=cubicle.role=isolate); \
	if [ -n "$$ids" ]; then docker rm -f $$ids; else echo "no isolates to reclaim"; fi

reset: ## Destroy the cluster and every volume. Irreversible.
	@printf 'This deletes all functions, logs and database volumes. Type YES to continue: ' && read ans && [ "$$ans" = YES ]
	-@docker rm -f $$(docker ps -aq --filter label=cubicle.role=isolate) 2>/dev/null || true
	-@docker rm -f cubicle-svc-postgres cubicle-svc-redis 2>/dev/null || true
	-@docker volume rm -f $$(docker volume ls -q --filter name=cubicle-) 2>/dev/null || true
	$(COMPOSE) down -v --remove-orphans
