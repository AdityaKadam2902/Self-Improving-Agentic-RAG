# ===========================================================================
# Multi-Stage Production Dockerfile: Self-Improving Agentic RAG Platform
# ===========================================================================

# Stage 1: Build React Frontend Assets
FROM node:18-alpine AS frontend-builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --prefer-offline --no-audit
COPY src/ ./src/
COPY public/ ./public/
RUN npm run build

# Stage 2: Python 3.12 Production Runtime
FROM python:3.12-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install minimal OS dependencies and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source tree and built frontend assets
COPY . .
COPY --from=frontend-builder /app/build ./frontend_build

# Configure dedicated non-root application user
RUN useradd -m -u 1001 appuser && \
    mkdir -p /app/vector_db && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
