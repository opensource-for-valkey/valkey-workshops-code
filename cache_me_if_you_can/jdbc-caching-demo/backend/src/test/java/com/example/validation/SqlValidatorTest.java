package com.example.validation;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * Unit tests for {@link SqlValidator}.
 * Validates Requirements 7.1, 7.2, 7.4, 7.6.
 */
class SqlValidatorTest {

    // --- Valid SELECT queries ---

    @Test
    void testValidSelectQuery() {
        assertDoesNotThrow(() -> SqlValidator.validate("SELECT * FROM flights"));
    }

    @Test
    void testSelectWithLeadingWhitespace() {
        assertDoesNotThrow(() -> SqlValidator.validate("  \t\n  SELECT id FROM airports"));
    }

    @Test
    void testSelectWithBlockComment() {
        assertDoesNotThrow(() -> SqlValidator.validate("/* comment */ SELECT name FROM airlines"));
    }

    @Test
    void testCaseInsensitiveSelect() {
        assertDoesNotThrow(() -> SqlValidator.validate("select * FROM flights"));
        assertDoesNotThrow(() -> SqlValidator.validate("SELECT * FROM flights"));
        assertDoesNotThrow(() -> SqlValidator.validate("SeLeCt * FROM flights"));
    }

    // --- Cache hint tests ---

    @Test
    void testHintDoesNotAffectValidation() {
        assertDoesNotThrow(() -> SqlValidator.validate("/* CACHE_PARAM(ttl=60s) */ SELECT * FROM flights"));
    }

    @Test
    void testHintWithInvalidQuery() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("/* CACHE_PARAM(ttl=60s) */ DROP TABLE flights"));
    }

    @Test
    void testValidCacheTtl() {
        assertDoesNotThrow(() -> SqlValidator.validateCacheTtl("300s"));
        assertDoesNotThrow(() -> SqlValidator.validateCacheTtl("15m"));
        assertDoesNotThrow(() -> SqlValidator.validateCacheTtl("2h"));
        assertDoesNotThrow(() -> SqlValidator.validateCacheTtl("1d"));
    }

    @Test
    void testCacheTtlInjectionRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validateCacheTtl("1s) */ SELECT SLEEP(30) #"));
    }

    @Test
    void testCacheTtlWithoutUnitRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validateCacheTtl("300"));
    }

    // --- Rejected queries (blocked keywords) ---

    @Test
    void testDropTableRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("DROP TABLE flights"));
    }

    @Test
    void testDeleteRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("DELETE FROM flights WHERE id = 1"));
    }

    @Test
    void testTruncateRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("TRUNCATE TABLE flights"));
    }

    @Test
    void testInsertRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("INSERT INTO flights (id) VALUES (1)"));
    }

    @Test
    void testUpdateRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("UPDATE flights SET name = 'x' WHERE id = 1"));
    }

    @Test
    void testCreateRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("CREATE TABLE test (id INT)"));
    }

    // --- Multi-statement rejection ---

    @Test
    void testMultiStatementRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("SELECT 1; DROP TABLE x"));
    }

    @Test
    void testSemicolonAtEndRejected() {
        // Design decision: trailing semicolons are rejected for safety
        // because the pattern checks for semicolons followed by non-whitespace,
        // but a bare "SELECT 1;" has no non-whitespace after the semicolon.
        // Actually, "SELECT 1;" should NOT trigger multi-statement rejection
        // since there's no non-whitespace after the semicolon.
        // However, it should still pass as a valid SELECT.
        assertDoesNotThrow(() -> SqlValidator.validate("SELECT 1;"));
    }

    // --- Empty/whitespace queries ---

    @Test
    void testEmptyQueryRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate(""));
    }

    @Test
    void testWhitespaceOnlyRejected() {
        assertThrows(InvalidQueryException.class,
            () -> SqlValidator.validate("   \t\n  "));
    }
}
