package com.example;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.Properties;

/**
 * BasicQueryCache — Demonstrates the AWS Advanced JDBC Wrapper's Remote Query Cache Plugin.
 *
 * This sample connects to a MariaDB database through the JDBC Wrapper, executes a SELECT
 * query with a cache hint, and shows the performance difference between a cache miss
 * (first execution, fetched from the database) and a cache hit (second execution, served
 * from Valkey).
 *
 * Run with: mvn compile exec:exec
 */
public class BasicQueryCache {

    // ─── ANSI Color Codes ──────────────────────────────────────────────────────
    private static final String RESET   = "\u001B[0m";
    private static final String BOLD    = "\u001B[1m";
    private static final String DIM     = "\u001B[2m";
    private static final String CYAN    = "\u001B[36m";
    private static final String GREEN   = "\u001B[32m";
    private static final String YELLOW  = "\u001B[33m";
    private static final String MAGENTA = "\u001B[35m";
    private static final String RED     = "\u001B[31m";

    public static void main(String[] args) throws Exception {

        // ─── JDBC Connection URL ───────────────────────────────────────────────────
        // The "jdbc:aws-wrapper:mysql://" prefix tells the AWS Advanced JDBC Wrapper
        // to intercept all JDBC calls and apply configured plugins (like the Remote
        // Query Cache Plugin). The underlying connection goes to MariaDB on port 3306.
        String dbHost = System.getenv().getOrDefault("DB_HOST", "localhost");
        String dbPort = System.getenv().getOrDefault("DB_PORT", "3306");
        String dbName = System.getenv().getOrDefault("DB_NAME", "flughafendb_large");
        String dbUser = System.getenv().getOrDefault("DB_USER", "flughafen_user");
        String dbPassword = System.getenv("DB_PASSWORD");
        if (dbPassword == null || dbPassword.isBlank()) {
            throw new IllegalStateException("Set DB_PASSWORD before running the sample");
        }
        String url = "jdbc:aws-wrapper:mysql://" + dbHost + ":" + dbPort + "/" + dbName;

        // ─── Connection Properties ─────────────────────────────────────────────────
        Properties props = new Properties();

        // Database credentials for the local MariaDB instance
        props.setProperty("user", dbUser);
        props.setProperty("password", dbPassword);

        // wrapperPlugins: Comma-separated list of JDBC Wrapper plugins to activate.
        // "remoteQueryCache" enables the Remote Query Cache Plugin, which automatically
        // caches query results in Valkey when a CACHE_PARAM SQL hint is present.
        props.setProperty("wrapperPlugins", "remoteQueryCache");

        // cacheEndpointAddrRw: The read/write endpoint for the Valkey cache server.
        // In production this would point to an ElastiCache/MemoryDB cluster; here we
        // use the local Valkey instance running on the default port 6379.
        props.setProperty("cacheEndpointAddrRw", "localhost:6379");

        // cacheUseSSL: Whether to use TLS when connecting to Valkey.
        // Set to "false" for local development; in production with ElastiCache/MemoryDB
        // you would set this to "true" for encrypted connections.
        props.setProperty("cacheUseSSL", "false");

        // ─── SQL Query with Cache Hint ─────────────────────────────────────────────
        // The "/* CACHE_PARAM(ttl=300s) */" prefix is a SQL hint recognized by the
        // Remote Query Cache Plugin. It instructs the plugin to:
        //   1. Check Valkey for a cached result before executing the query
        //   2. If not cached (MISS), execute against the database and store the result
        //      in Valkey with a TTL of 300 seconds (5 minutes)
        //   3. If cached (HIT), return the result directly from Valkey without hitting
        //      the database
        //
        // The hint is stripped before the query reaches the database, so it does not
        // affect SQL parsing or execution plans.
        String sql = "/* CACHE_PARAM(ttl=300s) */ "
                + "SELECT f.flightno, a1.name AS departure_airport, a2.name AS arrival_airport, "
                + "       f.departure, f.arrival, al.airlinename "
                + "FROM flight f "
                + "JOIN airport a1 ON f.`from` = a1.airport_id "
                + "JOIN airport a2 ON f.`to` = a2.airport_id "
                + "JOIN airline al ON f.airline_id = al.airline_id "
                + "WHERE f.departure > '2026-05-27' "
                + "ORDER BY f.departure "
                + "LIMIT 20";

        // ─── Banner ────────────────────────────────────────────────────────────────
        printBanner();

        // ─── Connection ────────────────────────────────────────────────────────────
        printSection("CONNECTING");
        System.out.printf("   Database:  %s%s%s%n", CYAN, "MariaDB @ localhost:3306/flughafendb_large", RESET);
        System.out.printf("   Cache:     %s%s%s%n", CYAN, "Valkey  @ localhost:6379", RESET);
        System.out.printf("   Plugin:    %s%s%s%n", CYAN, "remoteQueryCache", RESET);
        System.out.printf("   Cache TTL: %s%s%s%n", CYAN, "300s (5 minutes)", RESET);

        try (Connection conn = DriverManager.getConnection(url, props)) {
            System.out.printf("%n   %s✓%s Connected successfully%n", GREEN, RESET);

            // ─── Query Details ──────────────────────────────────────────────────────
            printSection("QUERY");
            printQueryBox(sql);

            // ─── Run 1: Expected CACHE MISS ─────────────────────────────────────────
            printSection("RUN 1 — CACHE MISS (fetching from MariaDB)");

            long startTime = System.currentTimeMillis();
            int rowCount = executeAndCount(conn, sql);
            long elapsed = System.currentTimeMillis() - startTime;

            printResult(1, rowCount, elapsed, false);

            // ─── Pause Between Executions ───────────────────────────────────────────
            // Sleep 1 second to clearly separate the two executions in time and allow
            // the cache write to complete before the second read.
            System.out.printf("%n   %s⏳ Waiting 1s for cache write to complete...%s%n", DIM, RESET);
            Thread.sleep(1000);

            // ─── Run 2: Expected CACHE HIT ──────────────────────────────────────────
            printSection("RUN 2 — CACHE HIT (served from Valkey)");

            startTime = System.currentTimeMillis();
            rowCount = executeAndCount(conn, sql);
            long elapsed2 = System.currentTimeMillis() - startTime;

            printResult(2, rowCount, elapsed2, true);

            // ─── Performance Comparison ─────────────────────────────────────────────
            printSection("PERFORMANCE COMPARISON");
            printComparisonTable(elapsed, elapsed2);

            // ─── Summary ────────────────────────────────────────────────────────────
            printSection("DONE");
            System.out.printf("   %s✅ Demo complete!%s%n", GREEN, RESET);
            System.out.printf("   The Remote Query Cache Plugin cached the query result in Valkey.%n");
            System.out.printf("   Subsequent executions are served from cache without hitting MariaDB.%n%n");
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════════
    // Output Formatting Helpers
    // ═══════════════════════════════════════════════════════════════════════════════

    private static void printBanner() {
        System.out.println();
        System.out.printf("   %s╔══════════════════════════════════════════════════════════════╗%s%n", CYAN, RESET);
        System.out.printf("   %s║%s   %s⚡ JDBC Remote Query Cache Demo%s                            %s║%s%n", CYAN, RESET, BOLD, RESET, CYAN, RESET);
        System.out.printf("   %s║%s      AWS Advanced JDBC Wrapper + Valkey                     %s║%s%n", CYAN, RESET, CYAN, RESET);
        System.out.printf("   %s╚══════════════════════════════════════════════════════════════╝%s%n", CYAN, RESET);
        System.out.println();
    }

    private static void printSection(String title) {
        System.out.println();
        System.out.printf("   %s─── %s%s%s %s───────────────────────────────────────────%s%n",
                DIM, RESET, BOLD + title + RESET, "", DIM, RESET);
    }

    private static void printQueryBox(String sql) {
        // Display the SQL in a nice box, stripping the hint for display
        String displaySql = sql.replace("/* CACHE_PARAM(ttl=300s) */ ", "");
        String hint = "/* CACHE_PARAM(ttl=300s) */";

        System.out.printf("   %sSQL Hint:%s  %s%s%s%n", DIM, RESET, YELLOW, hint, RESET);
        System.out.printf("   %sQuery:%s%n", DIM, RESET);
        // Split on SQL keywords that start a new clause, preserving the keyword
        String[] lines = displaySql.split("(?i)(?=\\bFROM\\b|\\bJOIN\\b|\\bWHERE\\b|\\bORDER BY\\b|\\bGROUP BY\\b|\\bLIMIT\\b|\\bHAVING\\b)");
        for (String line : lines) {
            String trimmed = line.trim();
            if (!trimmed.isEmpty()) {
                System.out.printf("     %s%s%s%n", CYAN, trimmed, RESET);
            }
        }
    }

    private static void printResult(int run, int rowCount, long elapsed, boolean cacheHit) {
        String icon = cacheHit ? "✓" : "⚡";
        String statusColor = cacheHit ? GREEN : YELLOW;
        String status = cacheHit ? "CACHE HIT" : "CACHE MISS";
        String source = cacheHit ? "Valkey cache" : "MariaDB";

        System.out.printf("%n   %s%s%s  Run %d complete%n", statusColor, icon, RESET, run);
        System.out.printf("      Rows:    %s%d%s%n", CYAN, rowCount, RESET);
        System.out.printf("      Latency: %s%d ms%s%n", MAGENTA, elapsed, RESET);
        System.out.printf("      Status:  %s%s%s%n", statusColor, status, RESET);
        System.out.printf("      Source:  %s%s%n", source, RESET);
    }

    private static void printComparisonTable(long dbTime, long cacheTime) {
        double speedup = cacheTime > 0 ? (double) dbTime / cacheTime : 0;

        System.out.printf("   %s┌──────────────────┬────────────────┬────────────────┬──────────────┐%s%n", DIM, RESET);
        System.out.printf("   %s│%s %-16s %s│%s %s%14s%s %s│%s %s%14s%s %s│%s %s%12s%s %s│%s%n",
                DIM, RESET, "Metric", DIM, RESET, YELLOW, "MariaDB", RESET, DIM, RESET, GREEN, "Valkey", RESET, DIM, RESET, MAGENTA, "Speedup", RESET, DIM, RESET);
        System.out.printf("   %s├──────────────────┼────────────────┼────────────────┼──────────────┤%s%n", DIM, RESET);
        System.out.printf("   %s│%s %-16s %s│%s %s%11d ms%s %s│%s %s%11d ms%s %s│%s %s%9.1fx%s    %s│%s%n",
                DIM, RESET, "Latency", DIM, RESET, YELLOW, dbTime, RESET, DIM, RESET, GREEN, cacheTime, RESET, DIM, RESET, MAGENTA, speedup, RESET, DIM, RESET);
        System.out.printf("   %s│%s %-16s %s│%s %s%14s%s %s│%s %s%14s%s %s│%s              %s│%s%n",
                DIM, RESET, "Source", DIM, RESET, YELLOW, "Database", RESET, DIM, RESET, GREEN, "Cache", RESET, DIM, RESET, DIM, RESET);
        System.out.printf("   %s└──────────────────┴────────────────┴────────────────┴──────────────┘%s%n", DIM, RESET);

        if (speedup >= 2) {
            System.out.printf("%n   %s🔥 Cache is %.1fx faster than direct database access!%s%n", BOLD, speedup, RESET);
        }
    }

    /**
     * Executes the given SQL query and returns the number of rows in the result set.
     * Uses a simple loop to drain the ResultSet and count rows.
     */
    private static int executeAndCount(Connection conn, String sql) throws Exception {
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {
            int count = 0;
            while (rs.next()) {
                count++;
            }
            return count;
        }
    }
}
