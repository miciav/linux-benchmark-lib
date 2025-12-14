# Minimal Dockerfile for Baseline plugin.
#
# Even in baseline mode, the container runner executes `python -m lb_ui.cli` with the
# host source mounted at runtime, so we need Python + the core runtime deps.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

# Optional runtime tools used by collectors and diagnostics.
RUN apt-get update && apt-get install -y \
    procps \
    sysstat \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/sbin:$PATH"

# Core runtime deps for running the CLI against mounted host code.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir psutil pandas numpy jc rich typer PyYAML pydantic rapidfuzz prompt_toolkit InquirerPy

WORKDIR /app
