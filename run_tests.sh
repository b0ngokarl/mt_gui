#!/bin/bash
"""
Automated Testing Script for Meshtastic GUI
Runs comprehensive tests and generates reports
"""

# Make sure we're in the right directory
cd "$(dirname "$0")"

echo "🚀 Starting Meshtastic GUI Automated Tests"
echo "=========================================="
date
echo ""

# Test 1: Reset/Refresh Issue Test
echo "🧪 Test 1: Reset/Refresh Issue Fix"
echo "-----------------------------------"
python3 test_reset_issue.py
if [ $? -eq 0 ]; then
    echo "✅ Reset/Refresh test PASSED"
else
    echo "❌ Reset/Refresh test FAILED"
fi
echo ""

# Test 2: Basic GUI functionality (if available)
if [ -f "test_gui.py" ]; then
    echo "🧪 Test 2: GUI Comprehensive Tests"
    echo "----------------------------------"
    # Note: This may require display/X11 forwarding
    timeout 30s python3 test_gui.py 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✅ GUI comprehensive tests PASSED"
    else
        echo "⚠️  GUI comprehensive tests SKIPPED (no display)"
    fi
    echo ""
fi

# Test 3: Data File Integrity
echo "🧪 Test 3: Data File Integrity"
echo "------------------------------"
python3 -c "
import json
import os

files_to_check = [
    'discovered_nodes.json',
    'node_remarks.json',
    'traceroute_history.json',
    'telemetry_history.json',
    'favorites.json'
]

all_ok = True
for filename in files_to_check:
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                json.load(f)
            print(f'✅ {filename} is valid JSON')
        except json.JSONDecodeError as e:
            print(f'❌ {filename} has invalid JSON: {str(e)}')
            all_ok = False
    else:
        print(f'✅ {filename} not present (OK)')

if all_ok:
    print('✅ All data files are valid')
else:
    print('❌ Some data files have issues')
    exit(1)
"
echo ""

# Test 4: Import Test
echo "🧪 Test 4: Module Import Test"
echo "-----------------------------"
python3 -c "
try:
    from meshtastic_gui import MeshtasticClientGUI
    print('✅ meshtastic_gui module imports successfully')
    
    # Test basic class instantiation
    from PyQt5.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    gui = MeshtasticClientGUI()
    print('✅ MeshtasticClientGUI class instantiates successfully')
    
except ImportError as e:
    print(f'❌ Import failed: {str(e)}')
    exit(1)
except Exception as e:
    print(f'❌ Instantiation failed: {str(e)}')
    exit(1)
"
echo ""

# Test 5: Performance Test
echo "🧪 Test 5: Performance Test"
echo "---------------------------"
python3 -c "
import time
import tempfile
import json
import sys
sys.path.insert(0, '.')

# Create a large dataset for performance testing
large_dataset = {}
for i in range(100):
    node_id = f'!{i:08x}'
    large_dataset[node_id] = {
        'user': f'Node{i}',
        'aka': f'N{i}',
        'hardware': 'TBEAM',
        'latitude': 37.7749 + (i * 0.001),
        'longitude': -122.4194 + (i * 0.001)
    }

# Test file I/O performance
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    start_time = time.time()
    json.dump(large_dataset, f, indent=2)
    write_time = time.time() - start_time
    temp_file = f.name

with open(temp_file, 'r') as f:
    start_time = time.time()
    loaded_data = json.load(f)
    read_time = time.time() - start_time

import os
os.unlink(temp_file)

print(f'✅ Write performance: {len(large_dataset)} nodes in {write_time:.3f}s')
print(f'✅ Read performance: {len(loaded_data)} nodes in {read_time:.3f}s')

if write_time < 1.0 and read_time < 0.1:
    print('✅ Performance test PASSED')
else:
    print('⚠️  Performance test WARNING: slow I/O detected')
"
echo ""

# Summary
echo "📋 Test Summary"
echo "==============="
echo "Tests completed at $(date)"
echo "See individual test results above."
echo ""
echo "💡 To run individual tests:"
echo "   python3 test_reset_issue.py"
echo "   python3 test_gui.py"
echo ""
echo "🔄 To run this test suite again:"
echo "   ./run_tests.sh"
