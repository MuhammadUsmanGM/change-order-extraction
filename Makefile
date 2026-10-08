.PHONY: check fix test lint format clean

check: lint format-check test

lint:
	ruff check src tests eval data

format-check:
	ruff format --check src tests eval data

fix:
	ruff check --fix src tests eval data
	ruff format src tests eval data

test:
	pytest tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
