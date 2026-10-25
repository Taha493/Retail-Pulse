# Container for the live demo (Hugging Face Spaces "Docker" SDK, Render, Fly.io...).
# The image builds the whole pipeline from the internet at build time,
# so the deployed report always ships with a fresh, validated warehouse.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY config ./config
COPY src ./src
COPY powerbi ./powerbi
COPY dashboard ./dashboard
RUN uv sync --frozen --no-dev && uv run --no-dev retail-bi all

# Hugging Face Spaces expects port 7860
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uv run --no-dev gunicorn --chdir dashboard app:server -b 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120"]
