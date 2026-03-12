# ============================================
# Stage 1: Build — compile C extensions
# ============================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build-time system deps (gcc, headers for lxml/xmlsec compilation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    pkg-config \
    libssl-dev \
    zlib1g-dev \
    libxml2-dev \
    libxslt1-dev \
    libxmlsec1-dev \
    libxmlsec1-openssl \
 && rm -rf /var/lib/apt/lists/*

# NOTE: IaC binaries are NOT in the app image.
# Runners (iac-runner, discovery-runner) are separate Docker images
# launched as K8s Jobs — each carries its own IaC tooling.

# Build Python deps into a virtual environment so we can copy it cleanly
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --no-binary lxml,xmlsec lxml xmlsec python3-saml
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage 2: Runtime — lean image with only what's needed
# ============================================
FROM python:3.11-slim

WORKDIR /app

# Install runtime-only system deps (no compilers, no -dev headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    dnsutils \
    curl \
    libxml2 \
    libxslt1.1 \
    xmlsec1 \
    libxmlsec1 \
    libxmlsec1-openssl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user BEFORE copying app code so we can use --chown on COPY
# (avoids a separate chown -R layer that duplicates the entire /app tree)
RUN groupadd -g 1000 appuser && \
    useradd -r -u 1000 -g appuser appuser && \
    mkdir -p /app/data/artifacts /app/config && \
    chown -R appuser:appuser /app

# Cache-bust arg (pass --build-arg CACHE_BUST=$(date +%s) to force fresh COPY)
ARG CACHE_BUST=0
# Copy application code — owned by appuser to avoid extra chown layer
COPY --chown=appuser:appuser . .

# app_config.default.json is already at /app root (shipped in repo)
# It provides ConfigManager fallback/merge for default settings

# Remove directories not needed in the container image
# (.dockerignore handles most of this, but belt-and-suspenders for safety)
RUN rm -rf venv __pycache__ .??* \
    iac_runner \
    discovery_runner \
    docs \
    dev_tools \
    tests \
    k8s \
    helm \
    ai_overview.md \
    investor_pitch

# Switch to non-root user
USER appuser

# Expose the port FastAPI will run on
EXPOSE 8000

# Command to run the application
CMD ["python", "main.py"]
