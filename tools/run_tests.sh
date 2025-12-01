#!/bin/bash

# Build the Docker image (only system dependencies, no app code)
docker build -t benchmark-app -f Dockerfile .

# Run the tests in a container with the current directory mounted as a volume
# This allows for faster development as code changes don't require rebuilding
docker run --rm \
  -v "$(pwd):/app" \
  -v "benchmark-app-venv:/app/.venv" \
  benchmark-app
