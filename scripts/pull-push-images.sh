#!/usr/bin/env bash
# ============================================================
# LogNest - Air-Gap Image Pull & Push Helper
# ============================================================
# Usage:
#   chmod +x scripts/pull-push-images.sh
#   ./scripts/pull-push-images.sh <PRIVATE_REGISTRY>
#
# Example:
#   ./scripts/pull-push-images.sh registry.internal:5000
# ============================================================
set -euo pipefail

REGISTRY="${1:-}"
IMAGES_FILE="$(dirname "$0")/../images.txt"

if [[ -z "${REGISTRY}" ]]; then
  echo "ERROR: Please provide your private registry address."
  echo "Usage: $0 <registry-host:port>"
  exit 1
fi

echo "==> Using registry: ${REGISTRY}"
echo ""

while IFS= read -r IMAGE; do
  # Skip comments and blank lines
  [[ "${IMAGE}" =~ ^#.*$ || -z "${IMAGE}" ]] && continue

  echo "--- Processing: ${IMAGE}"

  # Pull
  echo "    Pulling..."
  docker pull "${IMAGE}"

  # Tag
  # Strip any existing registry prefix (anything before first /)
  SHORT="${IMAGE#*/}"
  # If no slash in original (e.g. busybox:1.36), SHORT == IMAGE
  [[ "${SHORT}" == "${IMAGE}" ]] && SHORT="${IMAGE}"
  TARGET="${REGISTRY}/${SHORT}"

  echo "    Tagging as: ${TARGET}"
  docker tag "${IMAGE}" "${TARGET}"

  # Push
  echo "    Pushing..."
  docker push "${TARGET}"

  echo "    Done: ${TARGET}"
  echo ""
done < "${IMAGES_FILE}"

echo "==> All images pushed to ${REGISTRY}"
echo ""
echo "==> Update your values.yaml:"
echo "    global:"
echo "      imageRegistry: \"${REGISTRY}\""
