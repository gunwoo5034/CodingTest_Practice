FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY runner ./runner
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["uvicorn", "runner.app:app", "--host", "0.0.0.0", "--port", "8001"]
