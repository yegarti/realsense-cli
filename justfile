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

# Run what CI runs: `check` under GitHub Actions' env, then the tests on CI's oldest pyrealsense2
ci:
    GITHUB_ACTIONS=true just check
    GITHUB_ACTIONS=true UV_NO_SYNC=1 uv run --with pyrealsense2==2.58.1.10581 pytest -q
