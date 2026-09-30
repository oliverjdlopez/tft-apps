FROM ghcr.io/astral-sh/uv:0.10.12@sha256:72ab0aeb448090480ccabb99fb5f52b0dc3c71923bffb5e2e26517a1c27b7fec AS uv
FROM python:3.13-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --extra evals --no-install-project --no-dev
WORKDIR /workspace
CMD ["python", "-m", "uvicorn", "evals.langfuse.server:app", "--host", "0.0.0.0", "--port", "80"]
