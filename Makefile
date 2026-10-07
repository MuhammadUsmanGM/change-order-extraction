.PHONY: check fix test lint format clean

check: lint format-check test

lint:
	ruff check src tests

format-check:
	ruff format --check src tests

fix:
	ruff check --fix src tests
	ruff format src tests

test:
	pytest tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
