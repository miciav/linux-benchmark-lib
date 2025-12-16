FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Runtime deps (OpenMP) + build tools to allow compile-time tuning (STREAM_ARRAY_SIZE/NTIMES).
RUN apt-get update && apt-get install -y \
    gcc \
    make \
    libgomp1 \
    numactl \
    procps \
    sysstat \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Default: do nothing (used by Docker smoke tests).
CMD ["true"]

