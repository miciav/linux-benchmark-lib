FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

# Tools required by PTS install + common collectors.
RUN apt-get update && apt-get install -y \
    gdebi-core \
    unzip \
    procps \
    sysstat \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Phoronix Test Suite from the bundled .deb.
COPY lb_runner/plugins/phoronix_test_suite/assets/phoronix-test-suite_10.8.4_all.deb /tmp/phoronix-test-suite.deb
# Keep apt metadata available for gdebi dependency resolution.
RUN apt-get update && gdebi -n /tmp/phoronix-test-suite.deb && rm -f /tmp/phoronix-test-suite.deb && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/sbin:$PATH"

# Core runtime deps for running the CLI against mounted host code.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir psutil pandas numpy jc rich typer PyYAML pydantic rapidfuzz prompt_toolkit InquirerPy

# Match default PTS user-path override from pts_workloads.yaml
RUN mkdir -p /opt/lb/.phoronix-test-suite

WORKDIR /app
