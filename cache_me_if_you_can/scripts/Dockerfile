FROM mariadb:10.11

# Required SQL dump path, relative to the build context.
ARG DUMP_FILE

ENV MYSQL_DATABASE=flughafendb_large
ENV BAKED_DATADIR=/var/lib/mysql_baked

COPY ${DUMP_FILE} /tmp/flughafendb_dump.sql.gz
COPY scripts/docker-entrypoint-workshop.sh /usr/local/bin/docker-entrypoint-workshop.sh

# Initialize and populate a custom data directory so the resulting image is
# ready to serve the workshop data immediately after container startup.
RUN set -eux; \
    mkdir -p "$BAKED_DATADIR"; \
    chown -R mysql:mysql "$BAKED_DATADIR"; \
    mysql_install_db --user=mysql --datadir="$BAKED_DATADIR"; \
    mysqld --user=mysql --datadir="$BAKED_DATADIR" --skip-networking & \
    server_pid="$!"; \
    ready=0; \
    for attempt in $(seq 1 60); do \
        if mysqladmin -u root --socket=/run/mysqld/mysqld.sock ping --silent; then \
            ready=1; \
            break; \
        fi; \
        sleep 1; \
    done; \
    if [ "$ready" -ne 1 ]; then \
        echo "MariaDB did not become ready during image build" >&2; \
        kill "$server_pid" || true; \
        wait "$server_pid" || true; \
        exit 1; \
    fi; \
    mysql -u root --socket=/run/mysqld/mysqld.sock \
        -e "CREATE DATABASE IF NOT EXISTS flughafendb_large;"; \
    gunzip -c /tmp/flughafendb_dump.sql.gz | \
        mysql -u root --socket=/run/mysqld/mysqld.sock flughafendb_large; \
    mysql -u root --socket=/run/mysqld/mysqld.sock \
        -e "CREATE USER IF NOT EXISTS 'flughafen_user'@'%' IDENTIFIED BY 'disabled-during-build' ACCOUNT LOCK; \
            GRANT ALL PRIVILEGES ON flughafendb_large.* TO 'flughafen_user'@'%'; \
            GRANT PROCESS ON *.* TO 'flughafen_user'@'%';"; \
    mysql -u root --socket=/run/mysqld/mysqld.sock -e "FLUSH PRIVILEGES;"; \
    mysqladmin -u root --socket=/run/mysqld/mysqld.sock shutdown; \
    wait "$server_pid"; \
    rm /tmp/flughafendb_dump.sql.gz

RUN printf '%s\n' \
    '[mysqld]' \
    "datadir=$BAKED_DATADIR" \
    'bind-address=0.0.0.0' \
    'innodb_buffer_pool_size=1G' \
    'innodb_log_file_size=256M' \
    'innodb_flush_log_at_trx_commit=2' \
    'innodb_flush_method=O_DIRECT' \
    'max_connections=200' \
    'query_cache_size=0' \
    'query_cache_type=0' \
    > /etc/mysql/conf.d/baked_data.cnf

RUN chmod 0755 /usr/local/bin/docker-entrypoint-workshop.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-workshop.sh"]
CMD ["mysqld"]
