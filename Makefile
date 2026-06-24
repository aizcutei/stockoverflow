.PHONY: install run dev test docker-build docker-up docker-down clean

install:
	uv sync

run:
	uv run python main.py

dev:
	uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

test:
	uv run python -c "from backend.main import app; print('Import OK')"

docker-build:
	docker build -t stockoverflow .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

clean:
	rm -rf data/*.db __pycache__ .pytest_cache
	find . -name "*.pyc" -delete
