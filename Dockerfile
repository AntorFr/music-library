# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /app

# System deps for Pillow build
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev libwebp-dev zlib1g-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ---- Runtime stage ----
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/AntorFR/music-library"
LABEL org.opencontainers.image.description="Family media library manager — HA + Music Assistant"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Runtime libs only (no gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo libwebp7 zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application
COPY app/ app/

# Create data directories (thumbnails live in an ephemeral, non-volume path — see config)
RUN mkdir -p data/covers app/static/img

# Default cover placeholder
RUN python -c "from PIL import Image; img = Image.new('RGB', (300,300), '#374151'); img.save('app/static/img/default_cover.jpg', quality=85)"

# 8000 = full API + web frontend (HTTPS via reverse proxy)
# 8001 = dedicated, trimmed ESP API (expose on a fast internal/plaintext network)
EXPOSE 8000 8001

VOLUME /app/data

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Serves both the main app (:8000) and the ESP API (:8001) in one process.
CMD ["python", "-m", "app.server"]
