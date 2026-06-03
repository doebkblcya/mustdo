# Dependency Management

This project uses `uv` for Python dependency management.

## Files

```text
pyproject.toml    Direct runtime and development dependencies.
uv.lock           Fully resolved dependency lockfile. Commit this file.
.python-version   Project Python version.
.venv/            Local virtual environment. Do not commit this directory.
```

The project does not use `requirements.txt`. Keeping one dependency source avoids drift between `pyproject.toml`, lockfiles, and installed environments.

## Python Version

The project targets Python 3.11.

```text
3.11
```

## Common Commands

Install dependencies and create the local virtual environment:

```bash
uv sync
```

Run the API server:

```bash
uv run uvicorn app.main:app --reload
```

Run tests:

```bash
uv run pytest
```

Add a runtime dependency:

```bash
uv add <package>
```

Add a development dependency:

```bash
uv add --dev <package>
```

Remove a dependency:

```bash
uv remove <package>
```

Update the lockfile:

```bash
uv lock
```

## Lockfile

After changing dependencies, run:

```bash
uv sync
```

Then commit the updated `pyproject.toml` and `uv.lock`.
