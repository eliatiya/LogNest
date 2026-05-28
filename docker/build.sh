#!/bin/bash
# ============================================================
# LogNest — Build UI Docker Image
# ============================================================
# Usage:
#   ./docker/build.sh [REGISTRY]
#
# Examples:
#   ./docker/build.sh                          # builds lognest-ui:latest
#   ./docker/build.sh registry.internal:5000   # builds and pushes to private registry
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHART_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REGISTRY="${1:-}"
IMAGE_NAME="lognest-ui"
IMAGE_TAG="1.0.0"

echo "==> Building ${IMAGE_NAME}:${IMAGE_TAG}"

# Build from chart root so we can COPY files/app.py
docker build \
    -f "$SCRIPT_DIR/Dockerfile.ui" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -t "${IMAGE_NAME}:latest" \
    "$CHART_DIR"

echo "==> Built: ${IMAGE_NAME}:${IMAGE_TAG}"

if [ -n "${REGISTRY}" ]; then
    FULL_TAG="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
    FULL_LATEST="${REGISTRY}/${IMAGE_NAME}:latest"
    echo "==> Tagging: ${FULL_TAG}"
    docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${FULL_TAG}"
    docker tag "${IMAGE_NAME}:latest" "${FULL_LATEST}"
    echo "==> Pushing: ${FULL_TAG}"
    docker push "${FULL_TAG}"
    docker push "${FULL_LATEST}"
    echo "==> Done. Update values.yaml:"
    echo "    ui:"
    echo "      image:"
    echo "        repository: ${REGISTRY}/${IMAGE_NAME}"
    echo "        tag: \"${IMAGE_TAG}\""
fi
