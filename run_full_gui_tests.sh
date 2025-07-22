#!/bin/bash
# Automated full test plan for Meshtastic GUI
set -e

# 1. Run Python test scripts
python3 test_gui.py
python3 test_reset_issue.py

# 2. Run shell test script
bash run_tests.sh

# 3. Check for Python errors
for f in *.py; do
    echo "Checking $f for errors..."
    python3 -m py_compile "$f"
done

# 4. Check for JSON errors
for f in *.json; do
    echo "Checking $f for JSON validity..."
    python3 -c "import json; json.load(open('$f'))" || exit 1
done

# 5. Check for shell script errors
bash -n run_tests.sh

# 6. Print summary
if [ $? -eq 0 ]; then
    echo "\n✅ All automated tests and file checks passed!"
else
    echo "\n❌ Some tests or file checks failed."
fi
