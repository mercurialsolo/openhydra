#!/bin/bash
# Test script for hydra alias verification
# Tests all requirements from the task specification

set -e  # Exit on error

echo "=========================================="
echo "HYDRA ALIAS VERIFICATION TEST"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results
TESTS_PASSED=0
TESTS_FAILED=0

# Helper function for test results
pass_test() {
    echo -e "${GREEN}✓ PASS:${NC} $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

fail_test() {
    echo -e "${RED}✗ FAIL:${NC} $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

info() {
    echo -e "${BLUE}ℹ INFO:${NC} $1"
}

# 1. Source the aliases file
echo "=========================================="
echo "TEST 1: Source aliases and verify functions"
echo "=========================================="
source ~/.openhydra/aliases.sh

# Check if functions are defined
if type hydra &>/dev/null; then
    pass_test "hydra function is defined"
else
    fail_test "hydra function is not defined"
fi

if type hydra-status &>/dev/null; then
    pass_test "hydra-status function is defined"
else
    fail_test "hydra-status function is not defined"
fi

if type hydra-stop &>/dev/null; then
    pass_test "hydra-stop function is defined"
else
    fail_test "hydra-stop function is not defined"
fi

if type hydra-logs &>/dev/null; then
    pass_test "hydra-logs function is defined"
else
    fail_test "hydra-logs function is not defined"
fi

if type hydra-restart &>/dev/null; then
    pass_test "hydra-restart function is defined"
else
    fail_test "hydra-restart function is not defined"
fi

echo ""

# 2. Verify no server is running initially
echo "=========================================="
echo "TEST 2: Verify clean state (no server running)"
echo "=========================================="

if curl -s -f -o /dev/null --max-time 1 http://127.0.0.1:7070/api/v1/health 2>/dev/null; then
    fail_test "Server should not be running initially"
    # Clean up
    hydra-stop
    sleep 2
else
    pass_test "No server running initially (clean state)"
fi

echo ""

# 3. Test fresh start with hydra command
echo "=========================================="
echo "TEST 3: Fresh start - Execute 'hydra' command"
echo "=========================================="

info "Launching hydra with HYDRA_NO_BROWSER=1 to skip browser opening..."

# Run hydra in background to avoid browser opening blocking the test
HYDRA_NO_BROWSER=1 hydra &
HYDRA_PID=$!

# Wait for hydra to complete
wait $HYDRA_PID
HYDRA_EXIT_CODE=$?

if [ $HYDRA_EXIT_CODE -eq 0 ]; then
    pass_test "hydra command executed successfully (exit code 0)"
else
    fail_test "hydra command failed with exit code $HYDRA_EXIT_CODE"
fi

echo ""

# 4. Verify health endpoint responds
echo "=========================================="
echo "TEST 4: Verify health endpoint responds"
echo "=========================================="

# Give server a moment to fully start
sleep 2

MAX_RETRIES=30
RETRY_COUNT=0
HEALTH_OK=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s -f --max-time 1 http://127.0.0.1:7070/api/v1/health 2>/dev/null; then
        HEALTH_OK=true
        break
    fi
    sleep 1
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ "$HEALTH_OK" = true ]; then
    pass_test "Health endpoint /api/v1/health responds correctly"

    # Get health response details
    HEALTH_RESPONSE=$(curl -s http://127.0.0.1:7070/api/v1/health)
    info "Health response: $HEALTH_RESPONSE"
else
    fail_test "Health endpoint did not respond after ${MAX_RETRIES}s"
fi

echo ""

# 5. Verify PID file was created
echo "=========================================="
echo "TEST 5: Verify PID tracking"
echo "=========================================="

if [ -f ~/.openhydra/server.pid ]; then
    SERVER_PID=$(cat ~/.openhydra/server.pid)
    pass_test "PID file created: ~/.openhydra/server.pid (PID: $SERVER_PID)"

    # Verify process is actually running
    if ps -p "$SERVER_PID" > /dev/null 2>&1; then
        pass_test "Server process $SERVER_PID is running"
    else
        fail_test "Server process $SERVER_PID is not running"
    fi
else
    fail_test "PID file not created"
fi

echo ""

# 6. Test idempotency - run hydra again
echo "=========================================="
echo "TEST 6: Idempotency - Run 'hydra' again"
echo "=========================================="

info "Recording current PID before second hydra execution..."
FIRST_PID=$(cat ~/.openhydra/server.pid 2>/dev/null || echo "")

info "Executing hydra command again..."
HYDRA_NO_BROWSER=1 hydra
SECOND_EXIT_CODE=$?

if [ $SECOND_EXIT_CODE -eq 0 ]; then
    pass_test "Second hydra execution succeeded"
else
    fail_test "Second hydra execution failed with exit code $SECOND_EXIT_CODE"
fi

SECOND_PID=$(cat ~/.openhydra/server.pid 2>/dev/null || echo "")

if [ "$FIRST_PID" = "$SECOND_PID" ] && [ -n "$FIRST_PID" ]; then
    pass_test "Same server PID after second execution (no duplicate process)"
    info "PID remained: $FIRST_PID"
else
    fail_test "Different PID detected - duplicate process may have been created"
    info "First PID: $FIRST_PID, Second PID: $SECOND_PID"
fi

# Count openhydra serve processes
PROCESS_COUNT=$(ps aux | grep "openhydra serve" | grep -v grep | wc -l | tr -d ' ')
if [ "$PROCESS_COUNT" -eq 1 ]; then
    pass_test "Exactly one openhydra serve process running (no duplicates)"
else
    fail_test "Found $PROCESS_COUNT openhydra serve processes (expected 1)"
fi

echo ""

# 7. Test hydra-status
echo "=========================================="
echo "TEST 7: Test 'hydra-status' command"
echo "=========================================="

STATUS_OUTPUT=$(hydra-status 2>&1)
echo "$STATUS_OUTPUT"

if echo "$STATUS_OUTPUT" | grep -q "✓ Running"; then
    pass_test "hydra-status correctly reports server as running"
else
    fail_test "hydra-status does not report server as running"
fi

echo ""

# 8. Test hydra-logs
echo "=========================================="
echo "TEST 8: Test 'hydra-logs' command"
echo "=========================================="

if [ -f ~/.openhydra/server.log ]; then
    pass_test "Server log file exists: ~/.openhydra/server.log"

    LOGS_OUTPUT=$(hydra-logs 2>&1)
    if [ -n "$LOGS_OUTPUT" ]; then
        pass_test "hydra-logs produces output"
        info "Log lines: $(echo "$LOGS_OUTPUT" | wc -l | tr -d ' ')"
    else
        fail_test "hydra-logs produces no output"
    fi
else
    fail_test "Server log file does not exist"
fi

echo ""

# 9. Test custom port configuration
echo "=========================================="
echo "TEST 9: Test custom port configuration"
echo "=========================================="

info "Stopping current server..."
hydra-stop
sleep 2

info "Starting server on custom port 8888..."
OPENHYDRA_WEB_PORT=8888 HYDRA_NO_BROWSER=1 hydra &
wait $!

# Wait for server on custom port
sleep 3
CUSTOM_PORT_HEALTH=false
for i in {1..20}; do
    if curl -s -f --max-time 1 http://127.0.0.1:8888/api/v1/health 2>/dev/null; then
        CUSTOM_PORT_HEALTH=true
        break
    fi
    sleep 1
done

if [ "$CUSTOM_PORT_HEALTH" = true ]; then
    pass_test "Server responds on custom port 8888"
else
    fail_test "Server did not respond on custom port 8888"
fi

# Stop custom port server
if command -v lsof &> /dev/null; then
    CUSTOM_PID=$(lsof -ti :8888 2>/dev/null)
    if [ -n "$CUSTOM_PID" ]; then
        kill "$CUSTOM_PID" 2>/dev/null
        info "Stopped custom port server (PID: $CUSTOM_PID)"
    fi
fi

sleep 2

# Restart on default port for final tests
info "Restarting server on default port 7070..."
HYDRA_NO_BROWSER=1 hydra &
wait $!
sleep 3

echo ""

# 10. Test hydra-restart
echo "=========================================="
echo "TEST 10: Test 'hydra-restart' command"
echo "=========================================="

OLD_PID=$(cat ~/.openhydra/server.pid 2>/dev/null || echo "")

info "Executing hydra-restart..."
HYDRA_NO_BROWSER=1 hydra-restart &
wait $!

sleep 3

NEW_PID=$(cat ~/.openhydra/server.pid 2>/dev/null || echo "")

if [ -n "$NEW_PID" ] && [ "$OLD_PID" != "$NEW_PID" ]; then
    pass_test "Server restarted with new PID (old: $OLD_PID, new: $NEW_PID)"
else
    fail_test "Server restart may have failed (old: $OLD_PID, new: $NEW_PID)"
fi

# Verify new server is healthy
if curl -s -f --max-time 2 http://127.0.0.1:7070/api/v1/health 2>/dev/null; then
    pass_test "Restarted server is healthy"
else
    fail_test "Restarted server health check failed"
fi

echo ""

# 11. Test hydra-stop
echo "=========================================="
echo "TEST 11: Test 'hydra-stop' command"
echo "=========================================="

STOP_PID=$(cat ~/.openhydra/server.pid 2>/dev/null || echo "")

info "Executing hydra-stop..."
hydra-stop

sleep 2

# Verify server is stopped
if curl -s -f -o /dev/null --max-time 1 http://127.0.0.1:7070/api/v1/health 2>/dev/null; then
    fail_test "Server still responds after hydra-stop"
else
    pass_test "Server stopped successfully (health endpoint not responding)"
fi

# Verify process is not running
if [ -n "$STOP_PID" ] && ps -p "$STOP_PID" > /dev/null 2>&1; then
    fail_test "Server process $STOP_PID still running after stop"
else
    pass_test "Server process terminated"
fi

# Verify PID file removed
if [ ! -f ~/.openhydra/server.pid ]; then
    pass_test "PID file cleaned up"
else
    fail_test "PID file still exists after stop"
fi

echo ""

# Summary
echo "=========================================="
echo "TEST SUMMARY"
echo "=========================================="
echo -e "${GREEN}Tests Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Tests Failed: $TESTS_FAILED${NC}"
echo "Total Tests: $((TESTS_PASSED + TESTS_FAILED))"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ ALL TESTS PASSED${NC}"
    exit 0
else
    echo -e "${RED}✗ SOME TESTS FAILED${NC}"
    exit 1
fi
