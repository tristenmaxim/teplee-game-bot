FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

RUN uv sync --frozen --no-dev

EXPOSE 8000

# --no-sync: the venv is already frozen+no-dev from the build steps above;
# without it, `uv run` re-resolves and installs the dev group (ruff, pytest)
# into the container's writable layer on every start.
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
