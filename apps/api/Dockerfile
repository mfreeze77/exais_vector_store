FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/packages/svs_common:/app/apps/api:/app/apps/worker:/app/apps/model_gateway:/app/apps/instance_agent
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates postgresql-client && rm -rf /var/lib/apt/lists/*
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY packages /app/packages
COPY apps /app/apps
COPY configs /app/configs
COPY instances /app/instances
COPY tests /app/tests
COPY scripts /app/scripts
COPY evals /app/evals
COPY tickets /app/tickets
COPY charts /app/charts
COPY infra /app/infra
COPY runbooks /app/runbooks
COPY load-tests /app/load-tests
COPY migrations /app/migrations
COPY db /app/db
COPY VERSION alembic.ini docker-compose.yml /app/
EXPOSE 8080
CMD ["uvicorn", "svs_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
