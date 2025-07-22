import sys
import json
import os
import subprocess
import threading
import datetime
import time
import webbrowser
import re
import csv
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGroupBox, QComboBox, QLineEdit, QPushButton, 
                             QLabel, QMessageBox, QFileDialog, QTableWidget,
                             QTableWidgetItem, QTextEdit, QSpinBox, QCheckBox, QDialog, 
                             QScrollArea, QDoubleSpinBox, QInputDialog)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor

class CommandWorker(QThread):
    output_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()
    
    def __init__(self, command):
        super().__init__()
        self.command = command
    
    def run(self):
        try:
            # Execute the command
            process = subprocess.Popen(
                self.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Read output in real-time
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    self.output_ready.emit(output.strip())
            
            # Get any remaining output
            stdout, stderr = process.communicate()
            if stdout:
                self.output_ready.emit(stdout)
            if stderr:
                self.error_occurred.emit(f"Error: {stderr}")
                
        except Exception as e:
            self.error_occurred.emit(f"Failed to execute command: {str(e)}")
        finally:
            self.finished.emit()

class MeshtasticClientGUI(QWidget):
    def __init__(self):
        super().__init__()
        # File paths for data persistence
        self.settings_file = "meshtastic_settings.json"
        self.node_remarks_file = "node_remarks.json"
        self.discovered_nodes_file = "discovered_nodes.json"
        self.favorites_file = "favorites.json"
        self.node_keys_file = "node_keys.json"
        self.telemetry_stats_file = "telemetry_stats.json"
        self.connection_presets_file = "connection_presets.json"
        self.traceroute_history_file = "traceroute_history.json"
        self.telemetry_history_file = "telemetry_history.json"
        
        # Initialize data structures
        self.node_remarks = {}  # Store user remarks for discovered nodes {id: remark}
        self.discovered_nodes = {}  # Store discovered nodes with last seen info
        self.favorite_nodes = set()  # Store favorite node IDs
        self.traceroute_history = {}  # Store traceroute results {from_node: {to_node: [list of traceroute results]}}
        self.telemetry_history = {}  # Store telemetry results {from_node: {to_node: [list of telemetry results]}}
        self.connection_presets = {}  # Store connection presets {name: {method, address, remark}}
        self.column_visibility = {}  # Store column visibility state {column_name: bool}
        self.node_keys = {}  # Store public key history {node_id: [{'key': str, 'first_seen': str, 'last_seen': str}]}
        self.key_changes_pending = set()  # Store node IDs that have unacknowledged key changes
        self.telemetry_stats = {}  # Store min/max telemetry stats {node_id: {'battery': {'min': x, 'max': y, 'history': []}, ...}}
        self.location_service = "OpenStreetMap"  # Default location service
        
        # Command timing variables
        self.command_start_times = {}  # Track command start times {worker_id: start_time}
        self.log_entries = []  # Store log entries for potential export
        
        self.initUI()
        self.loadSettings()
        
        # Load device connections for smart preset matching
        self.loadDeviceConnections()
    
    def initUI(self):
        self.setWindowTitle("Meshtastic Client GUI")
        self.setGeometry(100, 100, 1200, 800)
        
        # Main layout
        main_layout = QVBoxLayout()
        
        # Top row: Connection settings (left) and Manual targets (right)
        top_row = QHBoxLayout()
        
        # Connection settings group (left)
        connection_group = QGroupBox("Connection Settings")
        connection_layout = QVBoxLayout()
        
        # First row: Connection method and address with presets
        first_row = QHBoxLayout()
        first_row.addWidget(QLabel("Method:"))
        self.connection_method = QComboBox()
        self.connection_method.addItems(["Serial Port", "IP Address", "Bluetooth"])
        self.connection_method.currentTextChanged.connect(self.onConnectionMethodChanged)
        self.connection_method.setMaximumWidth(120)
        first_row.addWidget(self.connection_method)
        
        # Add preset selector
        first_row.addWidget(QLabel("Preset:"))
        self.connection_preset = QComboBox()
        self.connection_preset.setMaximumWidth(150)
        self.connection_preset.currentTextChanged.connect(self.onPresetChanged)
        first_row.addWidget(self.connection_preset)
        
        # Preset management buttons
        self.save_preset_btn = QPushButton("Save Preset")
        self.save_preset_btn.clicked.connect(self.onSavePreset)
        self.save_preset_btn.setMaximumWidth(90)
        first_row.addWidget(self.save_preset_btn)
        
        self.delete_preset_btn = QPushButton("Delete")
        self.delete_preset_btn.clicked.connect(self.onDeletePreset)
        self.delete_preset_btn.setMaximumWidth(60)
        first_row.addWidget(self.delete_preset_btn)
        
        self.connection_label = QLabel("Port:")
        first_row.addWidget(self.connection_label)
        self.connection_input = QLineEdit()
        self.connection_input.setPlaceholderText("e.g., /dev/ttyUSB0")
        self.connection_input.setMaximumWidth(200)
        first_row.addWidget(self.connection_input)
        first_row.addStretch()
        
        # Second row: Remark field
        second_row = QHBoxLayout()
        second_row.addWidget(QLabel("Remark:"))
        self.remark_input = QLineEdit()
        self.remark_input.setPlaceholderText("Optional description/notes")
        self.remark_input.setMaximumWidth(300)
        second_row.addWidget(self.remark_input)
        second_row.addStretch()
        
        # Connection buttons - more compact
        button_layout = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.onConnect)
        self.connect_btn.setMaximumWidth(80)
        button_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.onDisconnect)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setMaximumWidth(80)
        button_layout.addWidget(self.disconnect_btn)
        
        # Settings buttons - more compact
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.saveSettings)
        self.save_btn.setMaximumWidth(60)
        button_layout.addWidget(self.save_btn)
        
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self.loadSettingsDialog)
        self.load_btn.setMaximumWidth(60)
        button_layout.addWidget(self.load_btn)
        
        # Reboot button
        self.reboot_btn = QPushButton("Reboot")
        self.reboot_btn.clicked.connect(self.onReboot)
        self.reboot_btn.setMaximumWidth(60)
        self.reboot_btn.setEnabled(False)  # Initially disabled
        self.reboot_btn.setToolTip("Reboot the connected device")
        button_layout.addWidget(self.reboot_btn)
        
        # Kill All Processes button
        self.kill_all_btn = QPushButton("Kill All")
        self.kill_all_btn.clicked.connect(self.onKillAllMeshtastic)
        self.kill_all_btn.setMaximumWidth(60)
        self.kill_all_btn.setStyleSheet("QPushButton { color: red; font-weight: bold; }")
        self.kill_all_btn.setToolTip("Kill all running meshtastic processes")
        button_layout.addWidget(self.kill_all_btn)
        
        button_layout.addStretch()
        
        # Add layouts to connection group
        connection_layout.addLayout(first_row)
        connection_layout.addLayout(second_row)
        connection_layout.addLayout(button_layout)
        connection_group.setLayout(connection_layout)
        
        # Device Configuration group (right)
        config_group = QGroupBox("Device Configuration")
        config_layout = QVBoxLayout()
        
        # Config controls row
        config_controls = QHBoxLayout()
        
        self.load_config_btn = QPushButton("Load Config")
        self.load_config_btn.clicked.connect(self.onLoadConfig)
        self.load_config_btn.setMaximumWidth(100)
        config_controls.addWidget(self.load_config_btn)
        
        self.save_config_btn = QPushButton("Save Config")
        self.save_config_btn.clicked.connect(self.onSaveConfig)
        self.save_config_btn.setMaximumWidth(100)
        self.save_config_btn.setEnabled(False)
        config_controls.addWidget(self.save_config_btn)
        
        self.reset_config_btn = QPushButton("Reset")
        self.reset_config_btn.clicked.connect(self.onResetConfig)
        self.reset_config_btn.setMaximumWidth(60)
        self.reset_config_btn.setEnabled(False)
        config_controls.addWidget(self.reset_config_btn)
        
        # Toggle visibility button
        self.toggle_config_btn = QPushButton("▶ Show Configuration")
        self.toggle_config_btn.clicked.connect(self.onToggleConfigVisibility)
        self.toggle_config_btn.setMaximumWidth(150)
        config_controls.addWidget(self.toggle_config_btn)
        
        config_controls.addStretch()
        config_layout.addLayout(config_controls)
        
        # Config editor (initially hidden)
        self.config_scroll = QScrollArea()
        self.config_scroll.setMaximumHeight(300)
        self.config_scroll.setVisible(False)
        
        self.config_widget = QWidget()
        self.config_form_layout = QVBoxLayout()
        self.config_widget.setLayout(self.config_form_layout)
        self.config_scroll.setWidget(self.config_widget)
        self.config_scroll.setWidgetResizable(True)
        
        config_layout.addWidget(self.config_scroll)
        config_group.setLayout(config_layout)
        
        # Add both groups to top row
        top_row.addWidget(connection_group)
        top_row.addWidget(config_group)
        
        # Actions section (middle)
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout()
        
        # Action controls
        action_controls = QHBoxLayout()
        action_controls.addWidget(QLabel("Target:"))
        self.target_select = QComboBox()
        self.target_select.setMaximumWidth(300)  # Increased width
        self.target_select.setMinimumWidth(200)  # Added minimum width
        self.target_select.setMaximumHeight(25)  # Added height constraint
        action_controls.addWidget(self.target_select)
        
        action_controls.addWidget(QLabel("Channel:"))
        self.channel_input = QSpinBox()
        self.channel_input.setMinimum(0)
        self.channel_input.setMaximum(255)
        self.channel_input.setValue(0)
        self.channel_input.setMaximumWidth(60)
        action_controls.addWidget(self.channel_input)
        
        self.traceroute_btn = QPushButton("Traceroute")
        self.traceroute_btn.clicked.connect(self.onTraceroute)
        self.traceroute_btn.setMaximumWidth(100)
        action_controls.addWidget(self.traceroute_btn)
        
        self.telemetry_btn = QPushButton("Get Telemetry")
        self.telemetry_btn.clicked.connect(self.onRequestTelemetry)
        self.telemetry_btn.setMaximumWidth(100)
        action_controls.addWidget(self.telemetry_btn)
        
        action_controls.addStretch()
        
        # Text messaging section - second row
        message_controls = QHBoxLayout()
        
        # Message type selector
        message_controls.addWidget(QLabel("Send:"))
        self.message_type = QComboBox()
        self.message_type.addItems(["To Channel", "To Node"])
        self.message_type.currentTextChanged.connect(self.onMessageTypeChanged)
        self.message_type.setMaximumWidth(100)
        message_controls.addWidget(self.message_type)
        
        # Message text input
        message_controls.addWidget(QLabel("Message:"))
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type your message here...")
        self.message_input.setMaximumWidth(200)
        self.message_input.returnPressed.connect(self.onSendMessage)  # Send on Enter key
        message_controls.addWidget(self.message_input)
        
        # Request ACK checkbox (for node messages)
        self.ack_cb = QCheckBox("Request ACK")
        self.ack_cb.setToolTip("Request acknowledgment when sending to a specific node")
        message_controls.addWidget(self.ack_cb)
        
        # Send button
        self.send_msg_btn = QPushButton("Send Message")
        self.send_msg_btn.clicked.connect(self.onSendMessage)
        self.send_msg_btn.setMaximumWidth(100)
        message_controls.addWidget(self.send_msg_btn)
        
        # Clear log button
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(self.onClearLog)
        self.clear_log_btn.setMaximumWidth(80)
        self.clear_log_btn.setStyleSheet("QPushButton { color: orange; font-weight: bold; }")
        self.clear_log_btn.setToolTip("Clear the command results log")
        message_controls.addWidget(self.clear_log_btn)
        
        message_controls.addStretch()
        
        # Results display
        self.results_display = QTextEdit()
        self.results_display.setMaximumHeight(150)
        self.results_display.setPlaceholderText("Command results will appear here...")
        
        actions_layout.addLayout(action_controls)
        actions_layout.addLayout(message_controls)
        actions_layout.addWidget(self.results_display)
        actions_group.setLayout(actions_layout)
        
        # Node list section (bottom)
        nodes_group = QGroupBox("Discovered Nodes")
        nodes_layout = QVBoxLayout()
        
        # Node list controls
        nodes_controls = QHBoxLayout()
        self.refresh_nodes_btn = QPushButton("Refresh Nodes")
        self.refresh_nodes_btn.clicked.connect(self.onRefreshNodes)
        self.refresh_nodes_btn.setMaximumWidth(100)
        nodes_controls.addWidget(self.refresh_nodes_btn)
        
        self.delete_node_btn = QPushButton("Delete Selected")
        self.delete_node_btn.clicked.connect(self.onDeleteSelectedNode)
        self.delete_node_btn.setMaximumWidth(100)
        nodes_controls.addWidget(self.delete_node_btn)
        
        self.export_csv_btn = QPushButton("Export CSV")
        self.export_csv_btn.clicked.connect(self.onExportCSV)
        self.export_csv_btn.setMaximumWidth(100)
        nodes_controls.addWidget(self.export_csv_btn)
        
        self.check_data_btn = QPushButton("Check Data")
        self.check_data_btn.clicked.connect(self.checkDataConsistency)
        self.check_data_btn.setMaximumWidth(100)
        self.check_data_btn.setStyleSheet("QPushButton { color: blue; font-weight: bold; }")
        self.check_data_btn.setToolTip("Check data consistency between JSON storage, GUI display, and CSV export")
        nodes_controls.addWidget(self.check_data_btn)
        
        self.reset_nodes_btn = QPushButton("Reset List")
        self.reset_nodes_btn.clicked.connect(self.onResetNodesList)
        self.reset_nodes_btn.setMaximumWidth(100)
        self.reset_nodes_btn.setStyleSheet("QPushButton { color: red; font-weight: bold; }")
        nodes_controls.addWidget(self.reset_nodes_btn)
        
        nodes_controls.addStretch()
        
        # Filter controls row
        filter_row = QHBoxLayout()
        
        # Text filter
        filter_row.addWidget(QLabel("Filter:"))
        self.node_filter_input = QLineEdit()
        self.node_filter_input.setPlaceholderText("Search nodes (ID, AKA, User, Hardware...)")
        self.node_filter_input.setMaximumWidth(250)
        self.node_filter_input.textChanged.connect(self.onNodeFilterChanged)
        filter_row.addWidget(self.node_filter_input)
        
        # Show only favorites checkbox
        self.favorites_only_cb = QCheckBox("Favorites only")
        self.favorites_only_cb.stateChanged.connect(self.onNodeFilterChanged)
        filter_row.addWidget(self.favorites_only_cb)
        
        # Column visibility button
        self.column_visibility_btn = QPushButton("Show/Hide Columns")
        self.column_visibility_btn.clicked.connect(self.onShowColumnDialog)
        self.column_visibility_btn.setMaximumWidth(120)
        filter_row.addWidget(self.column_visibility_btn)
        
        # Reset filters button
        self.reset_filters_btn = QPushButton("Reset All")
        self.reset_filters_btn.clicked.connect(self.onResetFilters)
        self.reset_filters_btn.setMaximumWidth(80)
        filter_row.addWidget(self.reset_filters_btn)
        
        # Location service selector
        filter_row.addWidget(QLabel("Maps:"))
        self.location_service_combo = QComboBox()
        self.location_service_combo.addItems(["OpenStreetMap", "Google Maps", "Bing Maps"])
        self.location_service_combo.setCurrentText(self.location_service)
        self.location_service_combo.currentTextChanged.connect(self.onLocationServiceChanged)
        self.location_service_combo.setMaximumWidth(120)
        filter_row.addWidget(self.location_service_combo)
        
        # Key acknowledgment button
        self.ack_keys_btn = QPushButton("Ack Key Changes")
        self.ack_keys_btn.clicked.connect(self.onAcknowledgeKeyChanges)
        self.ack_keys_btn.setMaximumWidth(120)
        self.ack_keys_btn.setEnabled(False)  # Initially disabled
        self.ack_keys_btn.setStyleSheet("QPushButton { color: red; font-weight: bold; }")
        filter_row.addWidget(self.ack_keys_btn)
        
        filter_row.addStretch()
        
        # Node table
        self.nodes_table = QTableWidget()
        self.nodes_table.setColumnCount(23)  # Added column for "Source"
        headers = ["Fav", "N", "User", "ID", "AKA", "Hardware", "Role", "Latitude", 
                   "Longitude", "Altitude", "Battery", "Ch.Util", "Tx.Util", 
                   "SNR", "Hops", "Channel", "LastHeard", "Last Seen by Client", "Traceroutes", "Telemetry", "Public Key", "Source", "Remark"]
        self.nodes_table.setHorizontalHeaderLabels(headers)
        self.nodes_table.setMaximumHeight(250)
        
        # Enable sorting for all columns
        self.nodes_table.setSortingEnabled(True)
        
        # Set favorite column width to be smaller
        self.nodes_table.setColumnWidth(0, 40)  # Favorite column
        
        # Connect to save remarks when cell is edited
        self.nodes_table.cellChanged.connect(self.onNodeCellChanged)
        
        # Connect to handle cell clicks for favorites
        self.nodes_table.cellClicked.connect(self.onNodeCellClicked)
        
        # Connect to handle double-clicks for detailed traceroute view
        self.nodes_table.cellDoubleClicked.connect(self.onNodeCellDoubleClicked)
        
        nodes_layout.addLayout(nodes_controls)
        nodes_layout.addLayout(filter_row)
        nodes_layout.addWidget(self.nodes_table)
        nodes_group.setLayout(nodes_layout)
        
        # Add all sections to main layout
        main_layout.addLayout(top_row)
        main_layout.addWidget(actions_group)
        main_layout.addWidget(nodes_group)
        
        self.setLayout(main_layout)
        
        # Set initial message type state
        self.onMessageTypeChanged("To Channel")  # Initialize with channel mode
    
    def onConnectionMethodChanged(self, method):
        """Handle connection method change"""
        # Update label and placeholder for connection input
        if method == "Serial Port":
            self.connection_label.setText("Port:")
            self.connection_input.setPlaceholderText("e.g., /dev/ttyUSB0")
        elif method == "IP Address":
            self.connection_label.setText("IP:")
            self.connection_input.setPlaceholderText("e.g., 192.168.1.100")
        elif method == "Bluetooth":
            self.connection_label.setText("BT Addr:")
            self.connection_input.setPlaceholderText("e.g., 00:11:22:33:44:55")
    
    def onLocationServiceChanged(self, service):
        """Handle location service change"""
        self.location_service = service
        # Save the preference
        self.saveSettings()
    
    def saveSettings(self):
        """Save current settings to file"""
        settings = {
            "connection_method": self.connection_method.currentText() if hasattr(self, 'connection_method') else "Serial Port",
            "connection_address": self.connection_input.text() if hasattr(self, 'connection_input') else "",
            "remark": self.remark_input.text() if hasattr(self, 'remark_input') else "",
            "default_channel": self.channel_input.value() if hasattr(self, 'channel_input') else 0,
            "location_service": getattr(self, 'location_service', 'OpenStreetMap'),
            "node_remarks": getattr(self, 'node_remarks', {})
        }
        
        try:
            settings_file = getattr(self, 'settings_file', 'meshtastic_settings.json')
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {str(e)}")
    
    def loadSettingsDialog(self):
        """Load settings from a selected file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Settings", "", "JSON Files (*.json);;All Files (*)")
        
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    settings = json.load(f)
                
                # Apply loaded settings
                if "connection_method" in settings:
                    index = self.connection_method.findText(settings["connection_method"])
                    if index >= 0:
                        self.connection_method.setCurrentIndex(index)
                
                if "connection_address" in settings:
                    self.connection_input.setText(settings["connection_address"])
                
                if "remark" in settings:
                    self.remark_input.setText(settings["remark"])
                
                if "default_channel" in settings:
                    self.channel_input.setValue(settings["default_channel"])
                
                QMessageBox.information(self, "Settings Loaded", f"Settings loaded from {file_path}")
                
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load settings: {str(e)}")
    
    def onAcknowledgeKeyChanges(self):
        """Acknowledge pending key changes"""
        if not self.key_changes_pending:
            return
        
        reply = QMessageBox.question(
            self, "Acknowledge Key Changes",
            f"Are you sure you want to acknowledge {len(self.key_changes_pending)} key change(s)?\n\n"
            f"This will mark the new keys as accepted and remove the warning highlighting.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.key_changes_pending.clear()
            self.ack_keys_btn.setEnabled(False)
            self.updateNodesTable()  # Refresh the table to remove highlighting
            self.saveNodeKeys()  # Save the acknowledgment
            QMessageBox.information(self, "Key Changes Acknowledged", "All pending key changes have been acknowledged.")
    
    def onPresetChanged(self, preset):
        """Handle preset change"""
        # Load preset details into fields
        if preset:
            for name, data in self.connection_presets.items():
                display_text = f"{name} ({data['method']}: {data['address']})"
                if display_text == preset:
                    self.connection_method.setCurrentText(data['method'])
                    self.connection_input.setText(data['address'])
                    self.remark_input.setText(data.get('remark', ""))
                    break
    
    def onSavePreset(self):
        """Save current connection as preset (cross-platform custom dialog)"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Save Preset")
        layout = QVBoxLayout(dialog)
        label = QLabel("Preset name:")
        layout.addWidget(label)
        name_input = QLineEdit()
        layout.addWidget(name_input)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        result = {'ok': False, 'name': ''}
        def accept():
            result['ok'] = True
            result['name'] = name_input.text()
            dialog.accept()
        def reject():
            dialog.reject()
        ok_btn.clicked.connect(accept)
        cancel_btn.clicked.connect(reject)
        dialog.setLayout(layout)
        if dialog.exec_() == QDialog.Accepted and result['ok'] and result['name']:
            name = result['name']
            self.connection_presets[name] = {
                "method": self.connection_method.currentText(),
                "address": self.connection_input.text(),
                "remark": self.remark_input.text()
            }
            self.updatePresetCombo()
            QMessageBox.information(self, "Preset Saved", f"Preset '{name}' saved.")
    
    def onDeletePreset(self):
        """Delete selected preset"""
        preset = self.connection_preset.currentText()
        if preset:
            for name in list(self.connection_presets.keys()):
                display_text = f"{name} ({self.connection_presets[name]['method']}: {self.connection_presets[name]['address']})"
                if display_text == preset:
                    del self.connection_presets[name]
                    self.updatePresetCombo()
                    QMessageBox.information(self, "Preset Deleted", f"Preset '{name}' deleted.")
                    break
    
    def updatePresetCombo(self):
        """Update the preset combo box with current presets"""
        current_selection = self.connection_preset.currentText()
        self.connection_preset.clear()
        self.connection_preset.addItem("")  # Empty option
        
        for name in sorted(self.connection_presets.keys()):
            preset = self.connection_presets[name]
            display_text = f"{name} ({preset['method']}: {preset['address']})"
            self.connection_preset.addItem(display_text)
        
        # Restore selection if it still exists
        if current_selection:
            index = self.connection_preset.findText(current_selection)
            if index >= 0:
                self.connection_preset.setCurrentIndex(index)
    
    def onConnect(self):
        """Connect to device"""
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.reboot_btn.setEnabled(True)
        self.results_display.append("Connected to device (simulated).")
    
    def onDisconnect(self):
        """Disconnect from device"""
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.reboot_btn.setEnabled(False)
        self.results_display.append("Disconnected from device (simulated).")
    
    def onReboot(self):
        """Reboot device"""
        QMessageBox.information(self, "Reboot", "Device rebooted (simulated).")
    
    def onKillAllMeshtastic(self):
        """Kill all meshtastic processes"""
        QMessageBox.information(self, "Kill All", "All Meshtastic processes killed (simulated).")
    
    def onLoadConfig(self):
        """Load configuration"""
        QMessageBox.information(self, "Load Config", "Configuration loaded (simulated).")
    
    def onSaveConfig(self):
        """Save configuration"""
        QMessageBox.information(self, "Save Config", "Configuration saved (simulated).")
    
    def onResetConfig(self):
        """Reset configuration"""
        QMessageBox.information(self, "Reset Config", "Configuration reset (simulated).")
    
    def onToggleConfigVisibility(self):
        """Toggle configuration visibility"""
        visible = not self.config_scroll.isVisible()
        self.config_scroll.setVisible(visible)
        self.toggle_config_btn.setText("\u25BC Hide Configuration" if visible else "\u25B6 Show Configuration")
    
    def onTraceroute(self):
        """Perform traceroute"""
        QMessageBox.information(self, "Traceroute", "Traceroute performed (simulated).")
    
    def onRequestTelemetry(self):
        """Request telemetry"""
        QMessageBox.information(self, "Telemetry", "Telemetry requested (simulated).")
    
    def onMessageTypeChanged(self, msg_type):
        """Handle message type change"""
        if msg_type == "To Channel":
            self.ack_cb.setEnabled(False)
        else:
            self.ack_cb.setEnabled(True)
    
    def onSendMessage(self):
        """Send message"""
        msg = self.message_input.text()
        if not msg:
            QMessageBox.warning(self, "Send Message", "Message cannot be empty.")
            return
        self.results_display.append(f"Message sent: {msg} (simulated)")
        self.message_input.clear()
    
    def onClearLog(self):
        """Clear log"""
        if hasattr(self, 'results_display'):
            self.results_display.clear()
    
    def onRefreshNodes(self):
        """Refresh nodes list"""
        self.results_display.append("Nodes list refreshed (simulated).")
    
    def onDeleteSelectedNode(self):
        """Delete the currently selected node from the discovered nodes list"""
        row = self.nodes_table.currentRow()
        if row >= 0:
            self.nodes_table.removeRow(row)
            self.results_display.append(f"Node at row {row} deleted (simulated).")
    
    def onExportCSV(self):
        """Export node data to CSV file"""
        file_path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "nodes.csv", "CSV Files (*.csv)")
        if file_path:
            try:
                with open(file_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([self.nodes_table.horizontalHeaderItem(i).text() for i in range(self.nodes_table.columnCount())])
                    for row in range(self.nodes_table.rowCount()):
                        writer.writerow([self.nodes_table.item(row, col).text() if self.nodes_table.item(row, col) else "" for col in range(self.nodes_table.columnCount())])
                QMessageBox.information(self, "Export CSV", f"Nodes exported to {file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Failed to export CSV: {str(e)}")
    
    def checkDataConsistency(self):
        """Check data consistency between JSON storage, GUI display, and CSV export"""
        QMessageBox.information(self, "Check Data", "Data consistency check complete (simulated).")
    
    def onResetNodesList(self):
        """Reset the nodes list"""
        self.nodes_table.setRowCount(0)
        self.results_display.append("Nodes list reset (simulated).")
    
    def onNodeFilterChanged(self):
        """Apply text filter and favorites filter to the node table"""
        # Simulated filter: just show message
        self.results_display.append("Node filter applied (simulated).")
    
    def onShowColumnDialog(self):
        """Show dialog for column visibility management"""
        QMessageBox.information(self, "Column Visibility", "Show/Hide columns dialog (simulated).")
    
    def onResetFilters(self):
        """Reset all filters and column visibility to default"""
        self.node_filter_input.clear()
        self.favorites_only_cb.setChecked(False)
        self.results_display.append("Filters reset (simulated).")
    
    def onNodeCellChanged(self, row, column):
        """Handle changes to node table cells, especially remarks"""
        self.results_display.append(f"Cell changed at row {row}, column {column} (simulated).")
    
    def onNodeCellClicked(self, row, column):
        """Handle cell clicks, especially for favorite column and location data"""
        self.results_display.append(f"Cell clicked at row {row}, column {column} (simulated).")
    
    def onNodeCellDoubleClicked(self, row, column):
        """Handle double-clicks for detailed traceroute view"""
        QMessageBox.information(self, "Traceroute Details", f"Detailed traceroute for row {row}, column {column} (simulated).")
    
    def loadSettings(self):
        """Load all settings and data from files"""
        # Simulated load
        self.results_display.append("Settings loaded (simulated).")
    
    def loadDeviceConnections(self):
        """Load device connections for smart preset matching"""
        # Simulated load
        self.results_display.append("Device connections loaded (simulated).")

    # Missing method implementations

# Main execution
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Meshtastic GUI")
    app.setApplicationVersion("1.0")
    
    # Create and show the main window
    window = MeshtasticClientGUI()
    window.show()
    
    # Run the application
    sys.exit(app.exec_())