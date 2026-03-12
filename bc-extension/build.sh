#!/bin/bash
# GPI Hub Integration - BC Extension Build Script
# This script validates the AL extension project structure.
# Actual compilation requires the AL Language extension in VS Code
# or the AL compiler (alc.exe) from the BC Docker sandbox.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "=== GPI Hub Integration - BC Extension Build ==="
echo "Project directory: $PROJECT_DIR"
echo ""

# Validate app.json exists
if [ ! -f "$PROJECT_DIR/app.json" ]; then
    echo "ERROR: app.json not found"
    exit 1
fi
echo "[OK] app.json found"

# Count AL files
TOTAL_AL=$(find "$PROJECT_DIR/src" -name "*.al" | wc -l)
echo "[OK] Found $TOTAL_AL AL source files"
echo ""

# List all objects by type
echo "--- Tables ---"
find "$PROJECT_DIR/src" -name "*.Table.al" -o -name "Table*.al" | sort
echo ""

echo "--- Table Extensions ---"
find "$PROJECT_DIR/src" -name "*.TableExtension.al" -o -name "TableExt*.al" | sort
echo ""

echo "--- Enums ---"
find "$PROJECT_DIR/src" -name "*.Enum.al" -o -name "Enum*.al" | sort
echo ""

echo "--- Codeunits ---"
find "$PROJECT_DIR/src" -name "*.Codeunit.al" | sort
echo ""

echo "--- Pages ---"
find "$PROJECT_DIR/src" -name "*.Page.al" -o -name "Page5*.al" | sort
echo ""

echo "--- Page Extensions ---"
find "$PROJECT_DIR/src" -name "PageExt*.al" | sort
echo ""

echo "--- Permission Sets ---"
find "$PROJECT_DIR/src" -name "*.PermissionSet.al" | sort
echo ""

echo "--- API Pages ---"
find "$PROJECT_DIR/src/api" -name "*.al" 2>/dev/null | sort
echo ""

# Validate no duplicate object IDs within same type
echo "=== Checking for duplicate object IDs ==="
TABLES=$(grep -rh "^table [0-9]" "$PROJECT_DIR/src" | awk '{print $2}' | sort)
DUPES=$(echo "$TABLES" | uniq -d)
if [ -n "$DUPES" ]; then
    echo "ERROR: Duplicate table IDs found: $DUPES"
    exit 1
fi
echo "[OK] No duplicate table IDs"

PAGES=$(grep -rh "^page [0-9]" "$PROJECT_DIR/src" | awk '{print $2}' | sort)
DUPES=$(echo "$PAGES" | uniq -d)
if [ -n "$DUPES" ]; then
    echo "ERROR: Duplicate page IDs found: $DUPES"
    exit 1
fi
echo "[OK] No duplicate page IDs"

CODEUNITS=$(grep -rh "^codeunit [0-9]" "$PROJECT_DIR/src" | awk '{print $2}' | sort)
DUPES=$(echo "$CODEUNITS" | uniq -d)
if [ -n "$DUPES" ]; then
    echo "ERROR: Duplicate codeunit IDs found: $DUPES"
    exit 1
fi
echo "[OK] No duplicate codeunit IDs"

echo ""
echo "=== Build Validation Complete ==="
echo ""
echo "To compile and package this extension:"
echo "  1. Open this folder in VS Code with the AL Language extension"
echo "  2. Download symbols: Ctrl+Shift+P > AL: Download Symbols"
echo "  3. Package: Ctrl+Shift+P > AL: Package"
echo "  4. The .app file will be created in the project root"
echo ""
echo "To publish to a BC Sandbox:"
echo "  1. Set launch.json to target your sandbox environment"
echo "  2. Press F5 (Publish) or Ctrl+F5 (Publish without debugging)"
echo "  3. Or upload the .app file via Extension Management in BC"
