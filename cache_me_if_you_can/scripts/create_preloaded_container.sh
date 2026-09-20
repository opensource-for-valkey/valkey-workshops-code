#!/bin/bash
# Supported workflow for generating the preloaded workshop MariaDB image.
set -euo pipefail

REGISTRY_USER="${1:-rlunaws}"
IMAGE_NAME="flughafendb_mariadb"
TAG="latest"
IMAGE_TAG="${REGISTRY_USER}/${IMAGE_NAME}:${TAG}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_ROOT/data"

if ! command -v docker >/dev/null 2>&1; then
    echo "Error: Docker is required but was not found on PATH." >&2
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/Dockerfile" ]; then
    echo "Error: Dockerfile not found at $SCRIPT_DIR/Dockerfile" >&2
    exit 1
fi

LATEST_DUMP=""
for dump_file in "$DATA_DIR"/*.sql.gz; do
    [ -e "$dump_file" ] || continue
    if [ -z "$LATEST_DUMP" ] || [ "$dump_file" -nt "$LATEST_DUMP" ]; then
        LATEST_DUMP="$dump_file"
    fi
done

if [ -z "$LATEST_DUMP" ]; then
    echo "Error: No SQL dump found in $DATA_DIR. Run scripts/dump_mariadb.sh first." >&2
    exit 1
fi

DUMP_FILE_RELATIVE="${LATEST_DUMP#"$PROJECT_ROOT"/}"
echo "Creating preloaded MariaDB image: $IMAGE_TAG"
echo "Using dump file: $LATEST_DUMP"
echo "Building image (this can take 10-30 minutes)..."

docker build \
    --tag "$IMAGE_TAG" \
    --build-arg "DUMP_FILE=$DUMP_FILE_RELATIVE" \
    --file "$SCRIPT_DIR/Dockerfile" \
    "$PROJECT_ROOT"

echo
echo "Image created: $IMAGE_TAG"
echo "Push with: docker push $IMAGE_TAG"
echo "Run with: WORKSHOP_DB_PASSWORD='<strong-password>' scripts/docker_setup_database_pro.sh $IMAGE_TAG"
