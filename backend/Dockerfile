# GPI Document Hub - Backend
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies.
#
# `curl` is used by the HEALTHCHECK below.
#
# The remaining packages are the OS-level shared libraries Playwright
# Chromium needs to launch headlessly inside this slim image. Without
# them the AP smoke DOM checker (`scripts/ap_smoke_walk_dom_check.py`)
# crashes with `libglib-2.0.so.0: cannot open shared object file`.
# The list mirrors what `playwright install-deps chromium` resolves to
# on Debian Bookworm/Trixie; pinning it here means a fresh
# `docker compose build --no-cache backend` keeps the smoke checker
# runnable without any post-rebuild manual step.
#
# This block only adds *capability*. It does NOT start the smoke
# checker, does NOT launch a browser at runtime, and does NOT change
# the application's startup behaviour.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    libx11-6 \
    libxcb1 \
    libxext6 \
    libxi6 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/

# Pre-fetch the Chromium binary that Playwright drives so the smoke
# DOM checker can run immediately after a clean rebuild. This step is
# skipped silently if `playwright` was not installed via requirements
# (e.g. on lean dev images that don't include the smoke harness).
# The browser binary is small relative to the OS deps already pulled
# above and only adds a one-off cost at build time.
RUN python -m playwright install chromium 2>/dev/null || \
    echo "playwright not in requirements; skipping browser pre-fetch"

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/api/health || exit 1

# Run with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
