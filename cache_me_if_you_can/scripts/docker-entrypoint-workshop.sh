#!/usr/bin/env bash
set -euo pipefail

DB_USER="${WORKSHOP_DB_USER:-flughafen_user}"
DB_PASSWORD="${WORKSHOP_DB_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"
DB_NAME="${MYSQL_DATABASE:-flughafendb_large}"
DATADIR="${BAKED_DATADIR:-/var/lib/mysql_baked}"
SOCKET="/run/mysqld/mysqld.sock"

if [[ ! "$DB_USER" =~ ^[a-zA-Z0-9_]+$ ]]; then
    echo "WORKSHOP_DB_USER may contain only letters, numbers, and underscores." >&2
    exit 1
fi

if [[ ! "$DB_NAME" =~ ^[a-zA-Z0-9_]+$ ]]; then
    echo "MYSQL_DATABASE may contain only letters, numbers, and underscores." >&2
    exit 1
fi

if [[ ! "$DB_PASSWORD" =~ ^[a-zA-Z0-9._~!@#%+=:-]{16,128}$ ]]; then
    echo "WORKSHOP_DB_PASSWORD must be 16-128 safe printable characters." >&2
    exit 1
fi

mkdir -p /run/mysqld
chown mysql:mysql /run/mysqld

mysqld \
    --user=mysql \
    --datadir="$DATADIR" \
    --skip-networking \
    --socket="$SOCKET" &
server_pid=$!

ready=0
for _ in {1..60}; do
    if mariadb-admin --user=root --socket="$SOCKET" ping --silent; then
        ready=1
        break
    fi
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    echo "MariaDB did not become ready for credential initialization." >&2
    kill "$server_pid" || true
    wait "$server_pid" || true
    exit 1
fi

mariadb --user=root --socket="$SOCKET" --execute \
    "CREATE USER IF NOT EXISTS '$DB_USER'@'%' IDENTIFIED BY '$DB_PASSWORD'; \
     ALTER USER '$DB_USER'@'%' IDENTIFIED BY '$DB_PASSWORD' ACCOUNT UNLOCK; \
     GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'%'; \
     GRANT PROCESS ON *.* TO '$DB_USER'@'%'; \
     FLUSH PRIVILEGES;"

mariadb-admin --user=root --socket="$SOCKET" shutdown
wait "$server_pid"

exec docker-entrypoint.sh "$@"
