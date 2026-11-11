# Contributing

## Environment setup

1. Install uv, just, Git, and Bash.
2. Install prek with `uv tool install prek`.
3. Clone the repository and enter its directory.
4. Run `just install` to synchronize all Python dependency groups and extras
   and install Git hooks for this repository. Development Python is 3.12;
   uv manages it through `.python-version`.

Run `just install` again after dependency changes. Recipes set `UV_NO_SYNC=1`,
so they do not silently synchronize the environment.

`just --list` lists development tasks. Task definitions live in `justfile`;
Git hook checks are configured in `.pre-commit-config.yml` and run through prek.

## Contributing code

1. Create a branch from `main` and make changes.
2. Run `just check`, then review automatic fixes, including `uv.lock`.
3. Run `just check-all` before opening a pull request.

Commit messages and pull request titles follow
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/), for example
`fix: handle invalid API responses`. The pre-commit hook checks staged changes,
applies fixes, and stops when files changed so you can review and stage them.

### Checks

```bash
just check                    # Run hooks on all Git-tracked files, applying fixes
just check mypy               # Run one configured hook
just check pyright
just check deptry
just format                   # Apply Ruff fixes and formatting
just lint                     # Check code and formatting without fixes
just type-check               # Run mypy and Pyright
just check-all                # Check environment, tests, docs, and all prek hooks
```

The hooks include Ruff, type analysis, documentation lint, spellchecking,
TOML/YAML validation, dependency declarations, lockfile consistency, actionlint,
and zizmor.

Deptry scans the library, including generated Protobuf imports, using metadata
from the project environment. Declare every directly imported runtime dependency;
optional extras remain runtime dependencies. `known_first_party` identifies this
library's absolute imports without suppressing missing-dependency findings.

`just check-all` validates the lockfile and installed environment, runs tests,
builds strict documentation with doctests, and runs all prek hooks, including
automatic fixes. Use `just build` to build a wheel under `dist/`.

### Tests and coverage

```bash
just test
just test tests/test_clients.py
just test -k 'clients or smoke'
just test --cov --cov-report=term-missing --cov-report=xml
```

Tests use three workers. Coverage is optional; the last command collects it for
the library, excluding generated Protobuf code, shows missing lines, and writes
`coverage.xml`. `.coverage`, `coverage.xml`, and other reports are ignored by Git.

### Development tasks

```bash
just doctor                   # Check local development tools
just package                  # Validate lockfile and installed dependencies
just build                    # Build a wheel distribution
just docs                     # Clean and build HTML documentation
just docs html doctest        # Build specific Sphinx targets
just docs-check               # Strict build, doctests, and LLM artifacts
just docs-linkcheck           # Check external links
just docs-serve               # Serve documentation on localhost:8000
```

## Maintenance

Edit Python dependencies in `pyproject.toml`, run `just install`, and commit the
resulting `uv.lock`. `just lock` updates only the lockfile. `just upgrade`
upgrades Python dependencies, synchronizes all groups and extras, and updates
hook revisions in `.pre-commit-config.yml`. Review the resulting changes and
rerun checks.

`just clean` removes build artifacts and caches. `just venv-remove`
(alias `destroy`) removes `.venv`; `just reinstall` removes both and runs installation.
Use `just install` for ordinary synchronization.

## Documentation

Update documentation and docstrings when changing public behavior. Follow the
[documentation guidelines](docs/pages/documentation-guidelines.rst) and run
`just docs-check`. Run `just docs-linkcheck` after changing external links.

## Context7 (optional)

[Context7](https://context7.com/docs/overview) can help coding agents look up
dependency documentation. Follow its [setup guide](https://context7.com/docs/installation)
to connect it to your agent or editor. Use local project sources for this library.
