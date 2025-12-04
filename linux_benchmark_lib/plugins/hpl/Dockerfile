ARG TARGETARCH
# Pull arch-specific base (tags available: 2.3-amd64, 2.3-arm64)
FROM miciav/hpl:2.3-${TARGETARCH}

ENV DEBIAN_FRONTEND=noninteractive

# Only add lightweight runtime tools needed by the collectors
RUN apt-get update && apt-get install -y \
    procps \
    sysstat \
    && rm -rf /var/lib/apt/lists/*

# Isolated env for the library and its deps
RUN python3 -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

# Copy plugin files
COPY . /app

# Install the library with its dependencies inside the venv
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .
