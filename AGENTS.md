# Repository Guidelines

## Project Structure & Module Organization

LearnAI is a Python 3.12+ tutoring engine using a `src` layout.
- `src/learnai/domain/`: mastery, evidence, planning, sessions, tutor contracts, and orchestration.
- `src/learnai/adapters/`: SymPy verification, YAML content loading, item generators, in-memory persistence, and a fake tutor.
- `content/quadratics/skills.yaml`: quadratic skill definitions.
- `tests/`: domain, adapter, content-contract, simulation, and architecture checks.
- `docs/superpowers/`: design specifications, implementation plans, and research notes. Distinguish planned features from implemented code.

## Build, Test, and Development Commands

Run commands from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m pytest tests/domain
python -m pytest --cov=learnai --cov-report=term-missing
```

These commands create an environment, install editable source with development dependencies, run the full suite or domain tests, and report coverage. Pytest defaults to quiet output. Packaging uses Hatchling; build a wheel with `python -m pip wheel . --no-deps`. There is currently no application server or CLI entry point.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` for modules and functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Follow existing type annotations, dataclasses, and protocol-based interfaces. Keep domain code dependent only on its own package and the standard-library modules permitted by `tests/test_domain_purity.py`; place external integrations in adapters. No formatter or linter is configured in `pyproject.toml`.

## Testing Guidelines

Use pytest with files named `test_*.py` and descriptive `test_*` functions. Mirror the affected package under `tests/`. Use Hypothesis for numerical properties and invariants, and deterministic seeds or fake clocks for reproducible simulations. Add regression tests for behavior changes and run the full suite before submitting. No minimum coverage threshold is configured. Preserve generator contract tests when changing SymPy: its version is deliberately constrained because grading depends on evaluation behavior.

## Commit & Pull Request Guidelines

Implementation history uses `feat:`, `fix:`, and `test:` prefixes; documentation commits also use concise imperative subjects such as “Add” or “Refine.” Match these patterns and keep commits focused. Pull requests should explain the behavior change, reference relevant issues or design plans, and report validation commands and results. Include screenshots when changing visual artifacts.
