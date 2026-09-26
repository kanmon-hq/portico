# ─── Builder Stage ──────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml ./
COPY src/ ./src/

# Build production wheel package
RUN uv build --wheel --out-dir /dist

# ─── Production Runner Stage ─────────────────────────────────────────
FROM python:3.14-slim AS runner

ARG EXTRAS="all"

LABEL maintainer="northfieldzz"
LABEL service="portico"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl wget ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"

# Install production package from wheel (with optional extras if specified)
COPY --from=builder /dist /dist
RUN WHEEL_FILE=$(ls /dist/*.whl | head -n 1) && \
    if [ -n "$EXTRAS" ]; then \
        uv pip install --system --no-cache "${WHEEL_FILE}[$EXTRAS]"; \
    else \
        uv pip install --system --no-cache "${WHEEL_FILE}"; \
    fi \
    && rm -rf /dist

EXPOSE 8001

CMD ["uvicorn", "portico.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
