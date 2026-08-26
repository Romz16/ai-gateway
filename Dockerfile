FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/gateway
COPY requirements.lock requirements-dev.lock ./
RUN pip install -r requirements.lock
COPY . .
RUN pip install --no-deps . && groupadd --gid 10001 gateway && useradd --uid 10001 --gid gateway --no-create-home gateway && mkdir -p /srv/secrets && chown gateway:gateway /srv/secrets
USER gateway
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--limit-concurrency", "150"]

FROM base AS test
ENV COVERAGE_FILE=/tmp/.coverage HYPOTHESIS_STORAGE_DIRECTORY=/tmp/.hypothesis
USER root
RUN pip install -r requirements-dev.lock
USER gateway
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS production
