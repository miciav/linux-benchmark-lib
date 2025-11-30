FROM python:3.12-slim

# Install workload dependencies
# coreutils is required for 'dd'
RUN apt-get update && apt-get install -y \
    coreutils \
    procps \
    sysstat \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/sbin:$PATH"

# Install core library dependencies
# This allows the container to run 'lb internal-run'
RUN pip install --no-cache-dir psutil typer rich pyyaml InquirerPy pandas numpy jc

WORKDIR /app

