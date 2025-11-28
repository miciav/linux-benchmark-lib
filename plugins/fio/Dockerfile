FROM python:3.12-slim

# Install workload dependencies
RUN apt-get update && apt-get install -y \
    fio \
    procps \
    sysstat \
    && rm -rf /var/lib/apt/lists/*

# Install core library dependencies
# This allows the container to run 'lb internal-run'
RUN pip install --no-cache-dir psutil typer rich pyyaml InquirerPy pandas numpy jc

WORKDIR /app

