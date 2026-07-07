FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/packages/svs_common:/app/apps/worker
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates postgresql-client && rm -rf /var/lib/apt/lists/*
COPY apps/worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY packages /app/packages
COPY apps/worker /app/apps/worker
COPY configs /app/configs
EXPOSE 8082
CMD ["python", "-m", "svs_worker.main"]
