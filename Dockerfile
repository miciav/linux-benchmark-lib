# Use the official uv base image matching the project's Python version
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Install system dependencies required by the benchmark tools
# Do this early as it's less likely to change than app code
RUN apt-get update && apt-get install -y \
    git \
    stress-ng \
    iperf3 \
    fio \
    sysstat \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Set uv environment variables for optimal container builds
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copy only the files needed for dependency installation first
# This allows better caching - dependencies only reinstall if these files change
COPY pyproject.toml  /app/

# Install dependencies
RUN uv sync --all-groups

# Add the virtual environment's bin directory to the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Reset the entrypoint from the base image
ENTRYPOINT []

# Default command - run tests
# When volume is mounted, we need to install the project in editable mode
# Use 'uv run' to execute pytest within the project's virtual environment where psutil is installed
CMD ["uv", "run", "pytest", "tests/"]
