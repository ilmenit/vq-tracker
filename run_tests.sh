#!/usr/bin/env bash
# Run POKEY VQ Tracker test suite
# Usage: ./run_tests.sh [options]
#   ./run_tests.sh              - run all tests
#   ./run_tests.sh -v           - verbose output
#   ./run_tests.sh test_name    - run specific test file (without .py)

set -e

cd "$(dirname "$0")"

if [ $# -eq 0 ] || [ "$1" = "-v" ]; then
    python3 -m unittest discover -s tests -v
else
    python3 -m unittest "tests.$1" -v
fi

echo ""
echo "ALL TESTS PASSED"
