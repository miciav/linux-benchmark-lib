FROM python:3.12-slim

# Install workload dependencies
RUN apt-get update && apt-get install -y \
    stress-ng \
    procps \
    sysstat \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/sbin:$PATH"

# Install core library dependencies needed by the CLI and runner when host code is mounted
RUN pip install --no-cache-dir \
    psutil \
    pandas \
    numpy \
    jc \
    rich \
    typer \
    PyYAML \
    pydantic \
    rapidfuzz \
    prompt_toolkit \
    InquirerPy

WORKDIR /app
