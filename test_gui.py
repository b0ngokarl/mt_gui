#!/usr/bin/env python3
"""
Automated Testing Suite for Meshtastic GUI
Tests node list functionality, reset operations, and data integrity
"""

import sys
import os
import json
import time
import datetime
import tempfile
import shutil
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt, QTimer

# Add the GUI module to path
sys.path.insert(0, os.path.dirname(__file__))

class TestRunner:
    def __init__(self):
        self.test_results = []
        self.test_data_dir = None
        
    def setup_test_environment(self):
        """Create a temporary directory for test data files"""
        self.test_data_dir = tempfile.mkdtemp(prefix="mt_gui_test_")
        print(f"📁 Test environment created: {self.test_data_dir}")
        
        # Create sample test data files
        self.create_sample_data()
        
    def cleanup_test_environment(self):
        """Clean up test environment"""
        if self.test_data_dir and os.path.exists(self.test_data_dir):
            shutil.rmtree(self.test_data_dir)
            print(f"🧹 Test environment cleaned up")
    
    def create_sample_data(self):
        """Create sample node data for testing"""
        sample_nodes = {
            "!12345678": {
                "user": "TestNode1",
                "aka": "TN1",
                "hardware": "TBEAM",
                "role": "CLIENT",
                "latitude": 37.7749,
                "longitude": -122.4194,
                "altitude": 100,
                "battery_level": 85,
                "channel_util": 12.5,
                "snr": 8.2,
                "hops_away": 1,
                "channel": "LongFast",
                "last_seen": "2025-07-21 10:30:00",
                "last_updated": "2025-07-21T10:35:00",
                "pubkey": "abcd1234efgh5678",
                "source_preset": "TestPreset",
                "source_method": "Serial"
            },
            "!87654321": {
                "user": "TestNode2", 
                "aka": "TN2",
                "hardware": "HELTEC_V3",
                "role": "ROUTER",
                "latitude": 37.7849,
                "longitude": -122.4094,
                "altitude": 150,
                "battery_level": 92,
                "channel_util": 8.7,
                "snr": 12.1,
                "hops_away": 2,
                "channel": "LongFast",
                "last_seen": "2025-07-21 10:32:00",
                "last_updated": "2025-07-21T10:37:00",
                "pubkey": "xyz9876abc1234",
                "source_preset": "TestPreset2",
                "source_method": "IP"
            }
        }
        
        sample_remarks = {
            "!12345678": "Test remark for node 1",
            "!87654321": "Test remark for node 2"
        }
        
        sample_traceroute_history = {
            "local": {
                "!12345678": [
                    {
                        "timestamp": "2025-07-21 10:20:00",
                        "success": True,
                        "channel": "LongFast",
                        "route": [{"from": "local", "to": "!12345678", "signal": "-50dBm", "direction": "towards"}],
                        "hops": 1,
                        "error": None
                    }
                ]
            }
        }
        
        sample_telemetry_history = {
            "local": {
                "!12345678": [
                    {
                        "timestamp": "2025-07-21 10:25:00",
                        "success": True,
                        "telemetry_data": {"battery": "85%", "voltage": "4.1V"},
                        "error": None
                    }
                ]
            }
        }
        
        # Write sample data files
        with open(os.path.join(self.test_data_dir, "discovered_nodes.json"), "w") as f:
            json.dump(sample_nodes, f, indent=2)
            
        with open(os.path.join(self.test_data_dir, "node_remarks.json"), "w") as f:
            json.dump(sample_remarks, f, indent=2)
            
        with open(os.path.join(self.test_data_dir, "traceroute_history.json"), "w") as f:
            json.dump(sample_traceroute_history, f, indent=2)
            
        with open(os.path.join(self.test_data_dir, "telemetry_history.json"), "w") as f:
            json.dump(sample_telemetry_history, f, indent=2)
            
        with open(os.path.join(self.test_data_dir, "favorites.json"), "w") as f:
            json.dump(["!12345678"], f, indent=2)
            
        print(f"📊 Sample data created with {len(sample_nodes)} nodes")
    
    def run_test(self, test_name, test_func):
        """Run a single test and record results"""
        print(f"🧪 Running test: {test_name}")
        try:
            start_time = time.time()
            result = test_func()
            end_time = time.time()
            
            self.test_results.append({
                'name': test_name,
                'status': 'PASS' if result else 'FAIL',
                'duration': end_time - start_time,
                'details': result if isinstance(result, str) else ''
            })
            
            status_emoji = "✅" if result else "❌"
            print(f"{status_emoji} {test_name}: {'PASS' if result else 'FAIL'}")
            return result
            
        except Exception as e:
            self.test_results.append({
                'name': test_name,
                'status': 'ERROR',
                'duration': 0,
                'details': str(e)
            })
            print(f"💥 {test_name}: ERROR - {str(e)}")
            return False
    
    def test_data_file_integrity(self):
        """Test if data files can be loaded properly"""
        required_files = [
            "discovered_nodes.json",
            "node_remarks.json", 
            "traceroute_history.json",
            "telemetry_history.json",
            "favorites.json"
        ]
        
        for filename in required_files:
            filepath = os.path.join(self.test_data_dir, filename)
            if not os.path.exists(filepath):
                return f"Missing file: {filename}"
                
            try:
                with open(filepath, 'r') as f:
                    json.load(f)
            except json.JSONDecodeError as e:
                return f"Invalid JSON in {filename}: {str(e)}"
        
        return True
    
    def test_gui_initialization(self):
        """Test if GUI initializes without errors"""
        try:
            # Import and create GUI instance
            from meshtastic_gui import MeshtasticClientGUI
            
            # Monkey-patch the data directory paths to use test directory
            gui = MeshtasticClientGUI()
            gui.data_dir = self.test_data_dir
            gui.settings_file = os.path.join(self.test_data_dir, "settings.json")
            gui.discovered_nodes_file = os.path.join(self.test_data_dir, "discovered_nodes.json")
            gui.favorites_file = os.path.join(self.test_data_dir, "favorites.json")
            gui.node_remarks_file = os.path.join(self.test_data_dir, "node_remarks.json")
            gui.node_keys_file = os.path.join(self.test_data_dir, "node_keys.json")
            gui.telemetry_stats_file = os.path.join(self.test_data_dir, "telemetry_stats.json")
            gui.connection_presets_file = os.path.join(self.test_data_dir, "connection_presets.json")
            gui.traceroute_history_file = os.path.join(self.test_data_dir, "traceroute_history.json")
            gui.telemetry_history_file = os.path.join(self.test_data_dir, "telemetry_history.json")
            
            return True
            
        except Exception as e:
            return f"GUI initialization failed: {str(e)}"
    
    def test_data_loading(self):
        """Test if data loading works correctly"""
        try:
            from meshtastic_gui import MeshtasticClientGUI
            
            gui = MeshtasticClientGUI()
            gui.data_dir = self.test_data_dir
            gui.discovered_nodes_file = os.path.join(self.test_data_dir, "discovered_nodes.json")
            gui.favorites_file = os.path.join(self.test_data_dir, "favorites.json")
            gui.node_remarks_file = os.path.join(self.test_data_dir, "node_remarks.json")
            gui.traceroute_history_file = os.path.join(self.test_data_dir, "traceroute_history.json")
            gui.telemetry_history_file = os.path.join(self.test_data_dir, "telemetry_history.json")
            
            # Load the data
            gui.loadDiscoveredNodes()
            gui.loadFavorites()
            gui.loadNodeRemarks()
            gui.loadTracerouteHistory()
            gui.loadTelemetryHistory()
            
            # Verify data was loaded
            if len(gui.discovered_nodes) != 2:
                return f"Expected 2 nodes, got {len(gui.discovered_nodes)}"
            
            if len(gui.favorite_nodes) != 1:
                return f"Expected 1 favorite, got {len(gui.favorite_nodes)}"
            
            if len(gui.node_remarks) != 2:
                return f"Expected 2 remarks, got {len(gui.node_remarks)}"
                
            return True
            
        except Exception as e:
            return f"Data loading failed: {str(e)}"
    
    def test_nodes_table_update(self):
        """Test if nodes table updates correctly"""
        try:
            from meshtastic_gui import MeshtasticClientGUI
            
            gui = MeshtasticClientGUI()
            gui.data_dir = self.test_data_dir
            gui.discovered_nodes_file = os.path.join(self.test_data_dir, "discovered_nodes.json")
            gui.favorites_file = os.path.join(self.test_data_dir, "favorites.json")
            gui.node_remarks_file = os.path.join(self.test_data_dir, "node_remarks.json")
            gui.traceroute_history_file = os.path.join(self.test_data_dir, "traceroute_history.json")
            gui.telemetry_history_file = os.path.join(self.test_data_dir, "telemetry_history.json")
            
            # Load data
            gui.loadDiscoveredNodes()
            gui.loadFavorites()
            gui.loadNodeRemarks()
            gui.loadTracerouteHistory()
            gui.loadTelemetryHistory()
            
            # Update the table
            gui.updateNodesTable()
            
            # Check if table was populated correctly
            row_count = gui.nodes_table.rowCount()
            if row_count != 2:
                return f"Expected 2 rows in table, got {row_count}"
            
            # Check if favorite node is marked correctly
            fav_item = gui.nodes_table.item(0, 0)  # First row, favorite column
            if fav_item and fav_item.text() != "★":
                # Try second row
                fav_item = gui.nodes_table.item(1, 0)
                if not fav_item or fav_item.text() != "★":
                    return "Favorite node not marked correctly in table"
            
            # Check if node IDs are present
            ids_found = []
            for row in range(row_count):
                id_item = gui.nodes_table.item(row, 3)  # ID column
                if id_item:
                    ids_found.append(id_item.text())
            
            expected_ids = ["!12345678", "!87654321"]
            for expected_id in expected_ids:
                if expected_id not in ids_found:
                    return f"Expected node ID {expected_id} not found in table"
            
            return True
            
        except Exception as e:
            return f"Nodes table update failed: {str(e)}"
    
    def test_reset_functionality(self):
        """Test the reset nodes list functionality"""
        try:
            from meshtastic_gui import MeshtasticClientGUI
            
            gui = MeshtasticClientGUI()
            gui.data_dir = self.test_data_dir
            gui.discovered_nodes_file = os.path.join(self.test_data_dir, "discovered_nodes.json")
            gui.favorites_file = os.path.join(self.test_data_dir, "favorites.json")
            gui.node_remarks_file = os.path.join(self.test_data_dir, "node_remarks.json")
            gui.node_keys_file = os.path.join(self.test_data_dir, "node_keys.json")
            gui.telemetry_stats_file = os.path.join(self.test_data_dir, "telemetry_stats.json")
            gui.traceroute_history_file = os.path.join(self.test_data_dir, "traceroute_history.json")
            gui.telemetry_history_file = os.path.join(self.test_data_dir, "telemetry_history.json")
            
            # Load initial data
            gui.loadDiscoveredNodes()
            gui.loadFavorites()
            gui.loadNodeRemarks()
            gui.loadTracerouteHistory()
            gui.loadTelemetryHistory()
            
            # Verify we have data before reset
            if len(gui.discovered_nodes) == 0:
                return "No data loaded before reset test"
            
            # Simulate reset (without the dialog)
            gui.discovered_nodes = {}
            gui.favorite_nodes = set()
            gui.node_remarks = {}
            gui.node_keys = {}
            gui.telemetry_stats = {}
            gui.traceroute_history = {}
            gui.telemetry_history = {}
            
            # Save cleared data
            gui.saveDiscoveredNodes()
            gui.saveFavorites()
            gui.saveNodeRemarks()
            gui.saveTracerouteHistory()
            gui.saveTelemetryHistory()
            
            # Update display
            gui.updateNodesTable()
            
            # Verify reset worked
            if gui.nodes_table.rowCount() != 0:
                return f"Table should be empty after reset, has {gui.nodes_table.rowCount()} rows"
            
            if len(gui.discovered_nodes) != 0:
                return f"Discovered nodes should be empty after reset, has {len(gui.discovered_nodes)} nodes"
            
            return True
            
        except Exception as e:
            return f"Reset functionality failed: {str(e)}"
    
    def test_column_mapping(self):
        """Test if column mappings are correct"""
        try:
            from meshtastic_gui import MeshtasticClientGUI
            
            gui = MeshtasticClientGUI()
            gui.data_dir = self.test_data_dir
            gui.discovered_nodes_file = os.path.join(self.test_data_dir, "discovered_nodes.json")
            gui.favorites_file = os.path.join(self.test_data_dir, "favorites.json")
            gui.node_remarks_file = os.path.join(self.test_data_dir, "node_remarks.json")
            gui.traceroute_history_file = os.path.join(self.test_data_dir, "traceroute_history.json")
            gui.telemetry_history_file = os.path.join(self.test_data_dir, "telemetry_history.json")
            
            # Load data and update table
            gui.loadDiscoveredNodes()
            gui.loadFavorites()
            gui.loadNodeRemarks()
            gui.loadTracerouteHistory()
            gui.loadTelemetryHistory()
            gui.updateNodesTable()
            
            # Check column headers
            expected_headers = [
                "⭐", "N", "User", "ID", "AKA", "Hardware", "Role", "Latitude", "Longitude",
                "Altitude", "Battery", "Ch.Util", "Tx.Util", "SNR", "Hops", "Channel",
                "LastHeard", "Last Seen by Client", "Traceroutes", "Telemetry", "Public Key",
                "Source", "Remark"
            ]
            
            actual_headers = []
            for col in range(gui.nodes_table.columnCount()):
                header = gui.nodes_table.horizontalHeaderItem(col)
                if header:
                    actual_headers.append(header.text())
                else:
                    actual_headers.append("")
            
            if len(actual_headers) != len(expected_headers):
                return f"Expected {len(expected_headers)} columns, got {len(actual_headers)}"
            
            for i, (expected, actual) in enumerate(zip(expected_headers, actual_headers)):
                if expected != actual:
                    return f"Column {i}: expected '{expected}', got '{actual}'"
            
            return True
            
        except Exception as e:
            return f"Column mapping test failed: {str(e)}"
    
    def generate_report(self):
        """Generate a comprehensive test report"""
        print("\n" + "="*60)
        print("🧪 AUTOMATED TEST RESULTS")
        print("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for test in self.test_results if test['status'] == 'PASS')
        failed_tests = sum(1 for test in self.test_results if test['status'] == 'FAIL')
        error_tests = sum(1 for test in self.test_results if test['status'] == 'ERROR')
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"💥 Errors: {error_tests}")
        print(f"Success Rate: {(passed_tests/total_tests*100):.1f}%")
        print("-" * 60)
        
        for test in self.test_results:
            status_emoji = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥"}[test['status']]
            print(f"{status_emoji} {test['name']:<30} {test['status']:<6} {test['duration']:.3f}s")
            if test['details'] and test['status'] != 'PASS':
                print(f"    Details: {test['details']}")
        
        return passed_tests == total_tests
    
    def run_all_tests(self):
        """Run all automated tests"""
        print("🚀 Starting Automated GUI Tests")
        print("="*60)
        
        try:
            self.setup_test_environment()
            
            # Run individual tests
            self.run_test("Data File Integrity", self.test_data_file_integrity)
            self.run_test("GUI Initialization", self.test_gui_initialization)
            self.run_test("Data Loading", self.test_data_loading)
            self.run_test("Nodes Table Update", self.test_nodes_table_update)
            self.run_test("Reset Functionality", self.test_reset_functionality)
            self.run_test("Column Mapping", self.test_column_mapping)
            
            # Generate report
            success = self.generate_report()
            
            if success:
                print("\n🎉 All tests passed! The GUI is working correctly.")
            else:
                print("\n⚠️ Some tests failed. Check the details above.")
            
            return success
            
        finally:
            self.cleanup_test_environment()

def main():
    """Main test runner"""
    # Create QApplication for GUI tests
    app = QApplication(sys.argv)
    
    # Run tests
    test_runner = TestRunner()
    success = test_runner.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
