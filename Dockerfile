FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ .
RUN npm run build


FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg curl libicu-dev xxd\
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.5.1-beta/N_m3u8DL-RE_v0.5.1-beta_linux-x64_20251029.tar.gz \
    | tar -xz -C /usr/local/bin \
    && chmod +x /usr/local/bin/N_m3u8DL-RE

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY fanzadl_webui/ ./fanzadl_webui/
COPY main.py .

RUN uv sync --frozen --no-dev

COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

RUN mkdir -p /download /image_cache

EXPOSE 8000

CMD ["uv", "run", "python", "main.py"]
