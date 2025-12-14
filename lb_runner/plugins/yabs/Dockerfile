FROM python:3.13-slim

# Install required tools for YABS
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    fio \
    iperf3 \
    bc \
    tar \
    sysstat \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy plugin sources only
COPY . /app

# Install runtime Python deps needed by the library when mounting host code
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir psutil pandas numpy jc rich typer PyYAML pydantic rapidfuzz prompt_toolkit InquirerPy

CMD ["bash"]
