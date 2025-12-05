FROM python:3.13-slim

# Install required tools for YABS
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    fio \
    iperf3 \
    bc \
    tar \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy plugin sources only
COPY . /app

# Install plugin dependencies (no deps to keep lean; host code mounted at runtime)
RUN pip install --no-cache-dir --upgrade pip

CMD ["bash"]
