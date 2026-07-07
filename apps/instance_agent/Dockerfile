FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/packages/svs_common:/app/apps/instance_agent
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates postgresql-client && rm -rf /var/lib/apt/lists/*
COPY apps/instance_agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY packages /app/packages
COPY apps/instance_agent /app/apps/instance_agent
COPY configs /app/configs
EXPOSE 8090
CMD ["uvicorn", "svs_instance_agent.main:app", "--host", "0.0.0.0", "--port", "8090"]
