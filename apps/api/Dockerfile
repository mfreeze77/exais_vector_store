FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/packages/svs_common:/app/apps/api:/app/apps/worker:/app/apps/model_gateway:/app/apps/instance_agent
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates postgresql-client && rm -rf /var/lib/apt/lists/*
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY packages /app/packages
COPY apps /app/apps
COPY configs /app/configs
COPY tests /app/tests
EXPOSE 8080
CMD ["uvicorn", "svs_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
