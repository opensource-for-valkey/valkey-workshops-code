#!/bin/bash
set -euo pipefail

IMAGE="${1:-${IMAGE:-rlunaws/flughafendb_mariadb:latest}}"
CONTAINER_NAME="${CONTAINER_NAME:-flughafendb_mariadb}"
HOST_PORT="${HOST_PORT:-13306}"
DB_USER="${WORKSHOP_DB_USER:-flughafen_user}"
DB_PASSWORD="${WORKSHOP_DB_PASSWORD:-}"

if [ -z "$DB_PASSWORD" ]; then
    echo "Error: Set WORKSHOP_DB_PASSWORD to a strong 16+ character password." >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "Error: Docker is required but was not found on PATH." >&2
    exit 1
fi

docker run -d --rm --name "$CONTAINER_NAME" \
    -p "127.0.0.1:$HOST_PORT:3306" \
    -e "WORKSHOP_DB_USER=$DB_USER" \
    -e "WORKSHOP_DB_PASSWORD=$DB_PASSWORD" \
    "$IMAGE"

echo "Waiting for MariaDB to start..."
ready=0
for attempt in {1..30}; do
    if docker exec "$CONTAINER_NAME" mariadb-admin ping \
        -h 127.0.0.1 -P 3306 -u "$DB_USER" "-p$DB_PASSWORD" --silent 2>/dev/null; then
        ready=1
        break
    fi
    echo "Attempt $attempt/30..."
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    echo "Error: MariaDB did not become ready in 30 seconds." >&2
    exit 1
fi

echo "Setup complete"
echo "  Image: $IMAGE"
echo "  Host: 127.0.0.1"
echo "  Port: $HOST_PORT"
echo "  User: $DB_USER"
echo "  Password: supplied through WORKSHOP_DB_PASSWORD"
echo "  Database: flughafendb_large"
