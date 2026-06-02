# =============================================================================
# Burdello Bum-Bum — Multi-stage Dockerfile
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a virtual environment
ENV VIRTUAL_ENV=/build/.venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# ---------------------------------------------------------------------------
# Stage 2: Production
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS production

WORKDIR /app

# Install runtime system dependencies (for sentence-transformers, numpy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /build/.venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY backend ./backend
COPY pyproject.toml ./

# Install the package itself (editable, no deps since they are in venv)
RUN pip install --no-cache-dir --no-deps -e .

# Non-root user
RUN useradd --create-home --shell /bin/bash bbuser && \
    chown -R bbuser:bbuser /app
USER bbuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# Stage 3: Development
# ---------------------------------------------------------------------------
FROM builder AS development

WORKDIR /app

ENV PATH="/build/.venv/bin:$PATH"

# Install dev tools directly in the builder venv
RUN pip install --no-cache-dir ruff mypy pytest pytest-asyncio pytest-cov

# Install the package in editable mode with dev dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY backend ./backend

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
