FROM python:3.12-slim

# Install workload dependencies
RUN apt-get update && apt-get install -y \
    stress-ng \
    procps \
    sysstat \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/sbin:$PATH"

# Install core library dependencies needed by the packaged CLI and collectors
RUN pip install --no-cache-dir psutil typer rich pyyaml InquirerPy pandas numpy jc

WORKDIR /app
