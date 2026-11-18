#!/bin/bash

# Check that every src/docpipe file committed in this branch meets the 80%
# line-coverage threshold. Reads coverage.xml produced by the Pytest stage —
# does NOT re-run pytest.
# Fails the build if any committed source file is below the threshold.
# Usage: ./scripts/check_pr_coverage.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MIN_COVERAGE=80
COVERAGE_XML="coverage.xml"

if [ ! -f "${COVERAGE_XML}" ]; then
    echo -e "${RED}${COVERAGE_XML} not found. Run pytest with --cov first.${NC}"
    exit 1
fi

echo -e "${YELLOW}Fetching committed Python files in this branch...${NC}"

MERGE_BASE=$(git merge-base HEAD origin/main)
COMMITTED=$(git diff --name-only --diff-filter=ACMR "${MERGE_BASE}"..HEAD | grep '\.py$' || true)

# Restrict to src/docpipe source files only
SRC_FILES=()
for file in $COMMITTED; do
    if [[ "$file" == src/docpipe/* ]] && [ -f "$file" ]; then
        SRC_FILES+=("$file")
    fi
done

if [ ${#SRC_FILES[@]} -eq 0 ]; then
    echo -e "${GREEN}No committed source files under src/docpipe/. Skipping coverage check.${NC}"
    exit 0
fi

echo -e "${YELLOW}Committed source files to check:${NC}"
printf '  %s\n' "${SRC_FILES[@]}"
echo ""

echo -e "${YELLOW}Checking per-file coverage against ${COVERAGE_XML}...${NC}"
echo "================================"

FAILED_FILES=()
PASSED_FILES=()
SKIPPED_FILES=()

for file in "${SRC_FILES[@]}"; do
    LINE_RATE=$(python3 - <<EOF
import xml.etree.ElementTree as ET, sys
tree = ET.parse("${COVERAGE_XML}")
root = tree.getroot()
# coverage.xml stores paths relative to the source root (src/docpipe/ stripped)
target = "${file}".removeprefix("src/")
for cls in root.iter("class"):
    if cls.get("filename", "") == target:
        print(cls.get("line-rate", "0"))
        sys.exit(0)
print("not_found")
EOF
)

    if [ "$LINE_RATE" = "not_found" ]; then
        echo -e "  ${YELLOW}SKIP${NC}  ${file} (not in coverage report)"
        SKIPPED_FILES+=("$file")
        continue
    fi

    PCT=$(python3 -c "print(int(float('${LINE_RATE}') * 100))")

    if [ "$PCT" -ge "$MIN_COVERAGE" ]; then
        echo -e "  ${GREEN}PASS${NC}  ${file}: ${PCT}%"
        PASSED_FILES+=("$file")
    else
        echo -e "  ${RED}FAIL${NC}  ${file}: ${PCT}% (need ${MIN_COVERAGE}%)"
        FAILED_FILES+=("$file")
    fi
done

echo ""
echo "================================"
echo -e "${YELLOW}Summary${NC}"
echo "================================"
echo "Committed src files : ${#SRC_FILES[@]}"
echo "Passed              : ${#PASSED_FILES[@]}"
echo "Failed              : ${#FAILED_FILES[@]}"
echo "Skipped (no data)   : ${#SKIPPED_FILES[@]}"

if [ ${#FAILED_FILES[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Files below the ${MIN_COVERAGE}% coverage threshold:${NC}"
    printf '  %s\n' "${FAILED_FILES[@]}"
    exit 1
fi

echo ""
echo -e "${GREEN}Coverage check passed.${NC}"
exit 0
