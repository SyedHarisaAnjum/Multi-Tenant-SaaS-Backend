FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, in their own layer: code changes don't re-install them.
# requirements.lock pins every transitive version, so rebuilds are reproducible.
COPY requirements.lock ./
RUN pip install --no-deps -r requirements.lock

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --no-create-home --shell /usr/sbin/nologin --uid 10001 appuser
USER appuser

EXPOSE 8000

# Ready = the app answers AND can reach PostgreSQL.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"

# No secrets in the image: all configuration comes from the environment at runtime.
# Worker processes: WEB_CONCURRENCY (uvicorn's own variable, default 1).
# Proxy headers are honored only from FORWARDED_ALLOW_IPS (uvicorn's default: 127.0.0.1).
# On SIGTERM, in-flight requests get up to 20 s to finish.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "--timeout-graceful-shutdown", "20"]
