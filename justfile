# List recipes
default:
    @just --list

# Run tests with coverage
test *args:
    uv run pytest --cov=realsense_cli --cov-report=term-missing {{args}}

# Type check
typecheck:
    uv run ty check realsense_cli/

# Lint and check formatting
lint:
    uv run ruff check .
    uv run ruff format --check .

# Format code and fix lint issues
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Run lint, typecheck and tests
check: lint typecheck test
