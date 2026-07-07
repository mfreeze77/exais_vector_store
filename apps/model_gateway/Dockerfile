FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/packages/svs_common:/app/apps/model_gateway
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates postgresql-client && rm -rf /var/lib/apt/lists/*
COPY apps/model_gateway/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY packages /app/packages
COPY apps/model_gateway /app/apps/model_gateway
COPY configs /app/configs
EXPOSE 8081
CMD ["uvicorn", "svs_model_gateway.main:app", "--host", "0.0.0.0", "--port", "8081"]
