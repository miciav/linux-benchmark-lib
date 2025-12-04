FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive

# Tooling needed to run the Top500 Ansible playbook and compile dependencies.
RUN apt-get update && apt-get install -y \
    sysstat \
    git \
    openssh-client \
    sshpass \
    build-essential \
    gfortran \
    curl \
    wget \
    sudo \
    openmpi-bin \
    libopenmpi-dev \
    libopenblas-dev \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (ansible + core library runtime deps).
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        ansible \
        psutil \
        typer \
        rich \
        pyyaml \
        InquirerPy \
        pandas \
        numpy \
        jc

WORKDIR /app

# Ensure Ansible finds python at the expected path
RUN ln -s /usr/local/bin/python3 /usr/bin/python3

# Include plugin source; host repo is mounted at runtime for development.
COPY . /app

# Pre-build HPL and MPICH using the existing Ansible logic.
# This ensures the container is ready-to-run without long setup times at runtime.
ENV HPL_ROOT=/opt/hpl
RUN ansible-playbook /app/linux_benchmark_lib/plugins/top500_benchmark/ansible/setup.yml \
    -i "localhost," \
    -c local \
    -e "hpl_root=${HPL_ROOT}" \
    -e "ssh_user=root" \
    -e "ssh_user_home=/root" \
    -e "assets_root=/app/linux_benchmark_lib/plugins/top500_benchmark/assets/top500-benchmark" \
    -v

RUN pip install --no-cache-dir --no-deps .
