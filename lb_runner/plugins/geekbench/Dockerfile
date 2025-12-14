FROM python:3.13-slim

# Install Geekbench prerequisites
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    tar \
    sysstat \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy plugin sources only
COPY . /app

# Upgrade pip and install runtime dependencies needed when host code is mounted
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir psutil pandas numpy jc rich typer PyYAML pydantic rapidfuzz prompt_toolkit InquirerPy

CMD ["bash"]
