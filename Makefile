COMPOSE_CMD=docker compose -p crud-api
COMPOSE_STOP_ALL=$(COMPOSE_CMD) stop

build:
	$(COMPOSE_CMD) build app

APP?=examples.asyncpg:app

run:
	$(COMPOSE_CMD) run -p 8000:8000 --rm app uvicorn --host 0.0.0.0 --reload $(APP)

install:
	$(COMPOSE_CMD) run --rm app poetry install

shell:
	$(COMPOSE_CMD) run --rm app bash

test:
	$(COMPOSE_CMD) run --rm app poetry run coverage run -m pytest tests
	$(COMPOSE_CMD) run --rm app poetry run coverage report
	$(COMPOSE_CMD) run --rm app poetry run coverage html

format:
	$(COMPOSE_CMD) run --rm app /bin/bash -c "\
		isort --settings /app/pyproject.toml crud_api examples tests && \
		black --config /app/pyproject.toml crud_api examples tests"
	$(COMPOSE_STOP_ALL)

lint:
	$(COMPOSE_CMD) run --rm app /bin/bash -c "\
		ruff /app/crud_api examples; \
		mypy /app/crud_api examples"
	$(COMPOSE_STOP_ALL)

clean:
	$(COMPOSE_CMD) rm -f -s -v
