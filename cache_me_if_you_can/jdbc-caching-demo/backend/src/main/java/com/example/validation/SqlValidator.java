package com.example.validation;

import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Validates SQL queries to ensure only SELECT statements are executed.
 * Strips cache hints and comments before validation to inspect the actual statement type.
 */
public class SqlValidator {

    private static final Pattern CACHE_HINT_PATTERN =
        Pattern.compile("^\\s*/\\*\\s*CACHE_PARAM\\([^)]*\\)\\s*\\*/\\s*", Pattern.CASE_INSENSITIVE);

    private static final Pattern SQL_COMMENT_PATTERN =
        Pattern.compile("(/\\*.*?\\*/|--[^\\n]*\\n?)", Pattern.DOTALL);

    private static final Pattern MULTI_STATEMENT_PATTERN =
        Pattern.compile(";\\s*\\S");

    private static final Pattern CACHE_TTL_PATTERN =
        Pattern.compile("^[1-9][0-9]*[smhd]$");

    private static final Set<String> BLOCKED_KEYWORDS = Set.of(
        "DROP", "DELETE", "TRUNCATE", "ALTER", "INSERT",
        "UPDATE", "CREATE", "GRANT", "REVOKE", "EXEC"
    );

    /**
     * Validates that the given SQL string is a safe SELECT query.
     *
     * @param sql the SQL string to validate
     * @throws InvalidQueryException if the query is not a valid SELECT statement
     */
    public static void validate(String sql) throws InvalidQueryException {
        if (sql == null || sql.isBlank()) {
            throw new InvalidQueryException("Only SELECT queries are allowed");
        }

        // 1. Strip the CACHE_PARAM hint prefix (if present)
        String stripped = CACHE_HINT_PATTERN.matcher(sql).replaceFirst("");

        // 2. Strip all SQL comments (block /* ... */ and line -- ...)
        stripped = SQL_COMMENT_PATTERN.matcher(stripped).replaceAll("");

        // 3. Trim leading/trailing whitespace
        stripped = stripped.trim();

        if (stripped.isEmpty()) {
            throw new InvalidQueryException("Only SELECT queries are allowed");
        }

        // 4. Check for semicolons followed by non-whitespace (multi-statement detection)
        Matcher multiStmtMatcher = MULTI_STATEMENT_PATTERN.matcher(stripped);
        if (multiStmtMatcher.find()) {
            throw new InvalidQueryException("Multi-statement queries are not allowed");
        }

        // 5. Extract the first word (case-insensitive)
        String firstWord = stripped.split("\\s+", 2)[0].toUpperCase();

        // 6. If first word is not SELECT, reject
        if (!"SELECT".equals(firstWord)) {
            throw new InvalidQueryException("Only SELECT queries are allowed");
        }

        // 7. Redundant safety net: reject if first word matches any blocked keyword
        if (BLOCKED_KEYWORDS.contains(firstWord)) {
            throw new InvalidQueryException("Only SELECT queries are allowed");
        }
    }

    /**
     * Validates a cache TTL before it is embedded in the JDBC cache hint.
     *
     * @param ttl duration expressed as a positive integer plus s, m, h, or d
     * @throws InvalidQueryException if the TTL could alter the SQL comment
     */
    public static void validateCacheTtl(String ttl) throws InvalidQueryException {
        if (ttl == null || !CACHE_TTL_PATTERN.matcher(ttl).matches()) {
            throw new InvalidQueryException(
                "Cache TTL must be a positive integer followed by s, m, h, or d"
            );
        }
    }
}
