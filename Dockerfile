FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/webhooks.db

WORKDIR /app

COPY requirements.txt .
# Optional: behind a TLS-intercepting proxy, pass a CA bundle with
#   docker build --secret id=pip_cert,src=/path/to/ca-bundle.pem .
RUN --mount=type=secret,id=pip_cert,required=false \
    if [ -f /run/secrets/pip_cert ]; then export PIP_CERT=/run/secrets/pip_cert; fi; \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home appuser && mkdir -p /data && chown appuser /data
USER appuser
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
