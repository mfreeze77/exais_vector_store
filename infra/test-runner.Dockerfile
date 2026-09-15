# Test runner for the repository's own test suite.
#
# It exists because the ad-hoc images on developer hosts drift from
# apps/api/requirements.txt: the one this repo's tickets name is often absent,
# and the nearest substitute was missing `jsonschema` (27 modules failed at
# collection) and `git` (provenance-recording scripts reported commit unknown).
#
# The repository is mounted at /work rather than COPYed, so the image stays
# small and never carries acquired corpora.
FROM python:3.12-slim
WORKDIR /work
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
    GIT_CONFIG_GLOBAL=/etc/gitconfig
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory /work
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
CMD ["python", "-m", "pytest", "-q"]
