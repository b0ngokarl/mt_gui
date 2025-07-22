#!/usr/bin/env python3
"""
Simple test to reproduce the reset/refresh issue
"""

import sys
import os
import json
import tempfile

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

def test_reset_refresh_issue():
    """Test the specific issue with reset and refresh"""
    print("🧪 Testing Reset/Refresh Issue")
    print("="*40)
    
    # Create temporary test directory
    test_dir = tempfile.mkdtemp(prefix="test_reset_")
    print(f"📁 Test directory: {test_dir}")
    
    try:
        # Create empty files (simulating reset)
        empty_files = [
            "discovered_nodes.json",
            "node_remarks.json", 
            "traceroute_history.json",
            "telemetry_history.json",
            "favorites.json"
        ]
        
        for filename in empty_files:
            filepath = os.path.join(test_dir, filename)
            with open(filepath, "w") as f:
                json.dump({}, f)  # Empty dict for most files
        
        # Favorites should be empty array
        with open(os.path.join(test_dir, "favorites.json"), "w") as f:
            json.dump([], f)
        
        print("✅ Created empty files (simulating reset)")
        
        # Now try to load and initialize GUI
        from meshtastic_gui import MeshtasticClientGUI
        
        # Create GUI but don't show it
        from PyQt5.QtWidgets import QApplication
        app = QApplication(sys.argv)
        
        gui = MeshtasticClientGUI()
        
        # Override file paths to use test directory
        gui.data_dir = test_dir
        gui.discovered_nodes_file = os.path.join(test_dir, "discovered_nodes.json")
        gui.favorites_file = os.path.join(test_dir, "favorites.json")
        gui.node_remarks_file = os.path.join(test_dir, "node_remarks.json")
        gui.traceroute_history_file = os.path.join(test_dir, "traceroute_history.json")
        gui.telemetry_history_file = os.path.join(test_dir, "telemetry_history.json")
        
        print("✅ GUI initialized")
        
        # Load data (should be empty after reset)
        gui.loadDiscoveredNodes()
        gui.loadFavorites()
        gui.loadNodeRemarks()
        gui.loadTracerouteHistory()
        gui.loadTelemetryHistory()
        
        print(f"📊 Loaded data: {len(gui.discovered_nodes)} nodes, {len(gui.favorite_nodes)} favorites")
        
        # Update table (should be empty)
        gui.updateNodesTable()
        print(f"📋 Table rows: {gui.nodes_table.rowCount()}")
        
        # Simulate parsing new node data (like after refresh)
        test_node_output = "│   1 │ TestUser   │ !12345678 │ TU   │ TBEAM    │ abcd1234 │ CLIENT │ 37.77° │ -122.41° │ 100m │ 85% │ 12.5% │ 8.7% │ 8.2 dB │ 1   │ 0 │ LongFast │ 10:30:00 │"
        
        print("🔄 Simulating node parse...")
        gui.parseNodeLine(test_node_output)
        
        print(f"📊 After parsing: {len(gui.discovered_nodes)} nodes")
        print(f"📋 Table rows: {gui.nodes_table.rowCount()}")
        
        if len(gui.discovered_nodes) > 0:
            node_id = list(gui.discovered_nodes.keys())[0]
            node_data = gui.discovered_nodes[node_id]
            print(f"📍 Sample node: {node_id} -> {node_data.get('user', 'N/A')}")
        
        # Test issue: parseNodeLine calls updateNodesTable() which could cause problems
        print("\n🔍 Checking for issues:")
        
        if gui.nodes_table.rowCount() == 0 and len(gui.discovered_nodes) > 0:
            print("✅ FIXED: parseNodeLine() no longer calls updateNodesTable() during parsing")
            print("   This prevents UI freezes and performance problems during refresh")
        else:
            print("⚠️  Issue found: parseNodeLine() calls updateNodesTable() for each parsed line")
            print("   This can cause UI freeze and performance problems during refresh")
        
        # Now simulate the complete refresh process by calling onRefreshFinished manually
        gui.updateNodesTable()  # This would be called by onRefreshFinished
        
        print(f"📋 Table rows after update: {gui.nodes_table.rowCount()}")
        
        if gui.nodes_table.rowCount() == len(gui.discovered_nodes):
            print("✅ FIXED: Table properly updated after refresh completion")
        else:
            print("⚠️  Issue: Table not properly updated after refresh")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        import shutil
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        print(f"🧹 Cleaned up test directory")

if __name__ == "__main__":
    test_reset_refresh_issue()
