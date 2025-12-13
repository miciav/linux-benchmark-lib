# Minimal Dockerfile for Baseline plugin
# This plugin performs no actual work, so we just need a minimal environment.
FROM alpine:latest

# Install python3 to allow potential future python-based execution within the container
RUN apk add --no-cache python3

CMD ["/bin/sh", "-c", "sleep 3600"]
