# Garmin Personal Podcasts

Syncs audio files from a Google Drive folder to Vercel Blob and serves
them as a private podcast RSS feed for PlayRun/Garmin.

## Setup (uv)

```bash
uv sync --group dev   # create .venv and install all dependencies
```

## Commands

```bash
uv run pytest tests/ -q   # full test suite
uv run pytest tests/unit -q  # fast unit tests only
uv run ruff check .       # lint
uv run ruff format .      # format
```

## Deploy

Dependencies come from `pyproject.toml` + `uv.lock` (Vercel installs
them with uv natively — no `requirements.txt` needed). Python version
is pinned to 3.14 via `.python-version` and `requires-python`.
