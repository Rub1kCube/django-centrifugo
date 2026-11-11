set positional-arguments
set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := false

# Cookiecutter sets the Python version when generating the project.
export DEV_PYTHON := "3.12"

# The environment is updated explicitly by install, upgrade, or reinstall.
export UV_NO_SYNC := "1"

export JUST_BIN := just_executable()
export JUST_FILE := justfile()

alias destroy := venv-remove
alias mypy := type-mypy
alias pyright := type-pyright

# Documentation module
mod _docs 'docs/justfile'

# List available tasks
_default:
    @"$JUST_BIN" --justfile "$JUST_FILE" --list --unsorted --list-submodules

_check-git:
    @command -v git >/dev/null 2>&1 || { printf 'git was not found in PATH\n' >&2; exit 1; }

_check-uv:
    @command -v uv >/dev/null 2>&1 || { printf 'uv was not found in PATH\n' >&2; exit 1; }

_check-all: _check-git _check-uv

# Check the local development tools
[group('dev')]
doctor: _check-all
    git --version
    uv --version
    "$JUST_BIN" --version

# Install the project, all dependency groups, and Git hooks
[group('dev')]
install: _check-all
    uv python pin "$DEV_PYTHON"
    uv sync --all-groups --all-extras
    uv run prek install --install-hooks

# Remove the environment and artifacts, then reinstall the project
[group('dev')]
reinstall: _check-all venv-remove clean install

# Update dependencies
[group('dev')]
upgrade: _check-all
    uv lock --upgrade
    uv sync --all-groups --all-extras
    uv run prek autoupdate

# Synchronize uv.lock with the current dependencies
[group('dev')]
lock: _check-uv
    uv lock

# Format code and apply Ruff fixes
[group('dev')]
format *paths: _check-uv
    uv run python -m ruff check --fix "$@"
    uv run python -m ruff format "$@"

# Run prek hooks on Git-tracked files, including automatic fixes
[group('dev')]
check *args: _check-uv
    uv run prek run --all-files "$@"

# Build a wheel distribution
[group('dev')]
build: _check-uv
    uv build --wheel

# Remove the virtual environment
[group('cleanup')]
venv-remove:
    rm -rf -- .venv

# Remove build, test, lint, and coverage artifacts
[group('cleanup')]
clean:
    rm -rf -- \
        .pytest_cache .ruff_cache .mypy_cache .hypothesis .precomcache \
        build dist wheelhouse .eggs .egg \
        docs/_build htmlcov .coverage coverage.xml coverage.json

# Run mypy
[group('typing')]
type-mypy *args: _check-uv
    uv run python -m mypy -n 4 "$@"

# Run Pyright
[group('typing')]
type-pyright *args: _check-uv
    uv run python -m pyright "$@"

# Run all type checkers
[group('typing')]
type-check: type-mypy type-pyright

# Run tests
[group('testing')]
test *args: _check-uv
    uv run python -m pytest -n 3 -q "$@"

# Run the local gRPC load benchmarks
[group('testing')]
bench *args: _check-uv
    uv run python -m benchmarks.run "$@"

# Check code and formatting; default to the entire project
[group('checks')]
lint *paths: _check-uv
    uv run python -m ruff check --no-fix "$@"
    uv run python -m ruff format --check --diff "$@"

# Check the lockfile, installed environment, and dependency compatibility
[group('checks')]
package: _check-uv
    uv lock --check
    uv sync --all-groups --all-extras --locked --check
    uv pip check
    uv audit --preview-features audit-command

# Check dependencies, tests, docs, and all prek hooks, including automatic fixes
[group('checks')]
check-all: package test docs-check
    uv run prek run --all-files

# Build the HTML documentation
[group('docs')]
docs +targets='clean html': (_docs::build targets)

# Build and serve the HTML documentation locally
[group('docs')]
docs-serve port='8000': docs
    uv run python -m http.server "{{ port }}" --bind 127.0.0.1 --directory docs/_build/html

# Build documentation strictly and run its doctests
[group('docs')]
docs-check: _docs::check

# Check external links in the documentation
[group('docs')]
docs-linkcheck: _docs::linkcheck
