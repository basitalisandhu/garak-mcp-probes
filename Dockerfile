# syntax=docker/dockerfile:1
#
# The garak-mcp CLI with garak and the MCP Python SDK. Build and run with:
#   docker build -t garak-mcp-probes .
#   docker run --rm garak-mcp-probes doctor --dry-run
#   docker run --rm -v "$PWD:/work" garak-mcp-probes run --config garak-mcp.yaml --probes test.Test --report-dir out
# Stdio servers must be commands available inside the image; "localhost" is the container.
#
# The base image is pinned by digest (python:3.12-slim, multi-arch index).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

# Build the wheel in a throwaway stage so the build backend never reaches the runtime image.
FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /src
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src/ src/
RUN pip wheel --no-deps --wheel-dir /wheels .

FROM ${PYTHON_IMAGE}
ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="garak-mcp-probes" \
      org.opencontainers.image.description="Run garak against your MCP servers: an agent generator and tool-misuse detectors" \
      org.opencontainers.image.source="https://github.com/basitalisandhu/garak-mcp-probes" \
      org.opencontainers.image.url="https://github.com/basitalisandhu/garak-mcp-probes" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOME=/home/app XDG_DATA_HOME=/home/app/.local/share XDG_CACHE_HOME=/home/app/.cache XDG_CONFIG_HOME=/home/app/.config
# garak depends on PyTorch. Install the CPU-only build from PyTorch's own index first, by itself,
# so the image does not carry GPU libraries; everything else comes from PyPI.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch
RUN --mount=type=bind,from=build,source=/wheels,target=/wheels \
    pip install /wheels/*.whl \
 && useradd --uid 1000 --user-group --create-home --home-dir /home/app --shell /usr/sbin/nologin app
# Mount a working directory with the configuration at /work; reports are written there.
WORKDIR /work
USER 1000:1000
ENTRYPOINT ["garak-mcp"]
CMD ["--help"]
