FROM python:3.12-slim

# Install workload dependencies
RUN apt-get update && apt-get install -y \
    iperf3 \
    libiperf0 \
    procps \
    sysstat \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/sbin:$PATH"

# Install core library dependencies
RUN pip install --no-cache-dir psutil typer rich pyyaml InquirerPy pandas numpy jc iperf3

WORKDIR /app
