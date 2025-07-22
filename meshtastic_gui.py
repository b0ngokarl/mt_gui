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
                             QScrollArea, QDoubleSpinBox)
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
    
    def onPresetChanged(self, preset_text):
        """Handle preset selection change"""
        if not preset_text:
            return
            
        # Extract preset name from display text (format: "name (method: address)")
        preset_name = preset_text.split(' (')[0] if ' (' in preset_text else preset_text
        
        if preset_name not in self.connection_presets:
            return
            
        preset = self.connection_presets[preset_name]
        
        # Update connection method
        method_index = self.connection_method.findText(preset['method'])
        if method_index >= 0:
            self.connection_method.setCurrentIndex(method_index)
        
        # Update address and remark
        self.connection_input.setText(preset['address'])
        self.remark_input.setText(preset.get('remark', ''))
    
    def onSavePreset(self):
        """Save current connection settings as a preset"""
        from PyQt5.QtWidgets import QInputDialog
        
        name, ok = QInputDialog.getText(
            self, 'Save Connection Preset', 
            'Enter preset name:',
            text=f"{self.connection_method.currentText()}")
        
        if ok and name.strip():
            name = name.strip()
            self.connection_presets[name] = {
                'method': self.connection_method.currentText(),
                'address': self.connection_input.text().strip(),
                'remark': self.remark_input.text().strip()
            }
            self.updatePresetCombo()
            self.saveConnectionPresets()
            QMessageBox.information(self, "Preset Saved", f"Connection preset '{name}' saved successfully!")
    
    def onDeletePreset(self):
        """Delete the selected preset"""
        current_preset = self.connection_preset.currentText()
        if not current_preset:
            QMessageBox.warning(self, "Warning", "Please select a preset to delete.")
            return
            
        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete the preset '{current_preset}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if current_preset in self.connection_presets:
                del self.connection_presets[current_preset]
                self.updatePresetCombo()
                self.saveConnectionPresets()
                QMessageBox.information(self, "Preset Deleted", f"Preset '{current_preset}' deleted successfully!")
    
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
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        if not address:
            QMessageBox.warning(self, "Warning", "Please enter a connection address.")
            return
        
        # TODO: Implement actual connection logic here
        QMessageBox.information(self, "Connection", f"Connecting to {method}: {address}")
        
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.reboot_btn.setEnabled(True)  # Enable reboot button when connected
        self.updateTargetCombo()
    
    def onDisconnect(self):
        # TODO: Implement actual disconnection logic here
        QMessageBox.information(self, "Disconnection", "Disconnected from device.")
        
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.reboot_btn.setEnabled(False)  # Disable reboot button when disconnected
    
    def onReboot(self):
        """Reboot the connected device"""
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        if not address:
            QMessageBox.warning(self, "Warning", "Please connect to a device first.")
            return
        
        # Confirm reboot action
        reply = QMessageBox.question(
            self, "Confirm Reboot", 
            f"Are you sure you want to reboot the connected device?\n\n"
            f"Connection: {method} - {address}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Build reboot command based on connection method
        if method == "Serial Port":
            cmd = f'meshtastic --port {address} --reboot'
        elif method == "IP Address":
            cmd = f'meshtastic --host {address} --reboot'
        else:  # Bluetooth
            cmd = f'meshtastic --ble {address} --reboot'
        
        self.results_display.append(f"Rebooting device: {cmd}\n")
        self.results_display.append("=" * 50 + "\n")
        
        # Log command start with timestamp
        self.logMessage(f"REBOOT START: {cmd}", 'command')
        command_start_time = time.time()
        
        # Disable all command buttons while reboot command is running
        self.setButtonsEnabled(False, "Kill All")
        self.reboot_btn.setText("Rebooting...")
        
        # Execute the command in a separate thread
        self.reboot_worker = CommandWorker(cmd)
        self.reboot_worker.output_ready.connect(self.onCommandOutput)
        self.reboot_worker.error_occurred.connect(self.onCommandError)
        self.reboot_worker.finished.connect(self.onRebootFinished)
        
        # Store timing info
        worker_id = id(self.reboot_worker)
        self.command_start_times[worker_id] = command_start_time
        self.reboot_worker.start()
    
    def onKillAllMeshtastic(self):
        """Kill all running meshtastic CLI processes (not the GUI)"""
        reply = QMessageBox.question(
            self, "Kill Meshtastic CLI Processes",
            "This will terminate all running meshtastic CLI processes.\n\n"
            "This includes:\n"
            "• meshtastic --nodes commands\n"
            "• meshtastic --traceroute commands\n"
            "• meshtastic --request-telemetry commands\n"
            "• Other meshtastic CLI operations\n\n"
            "The GUI will remain running.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self.results_display.append("Killing meshtastic CLI processes...\n")
        self.results_display.append("=" * 50 + "\n")
        
        # Log command start with timestamp
        self.logMessage("KILL ALL START: Terminating meshtastic CLI processes", 'command')
        command_start_time = time.time()
        
        # Set specific button state - Kill All should be disabled during execution
        # but other buttons can remain in their current disabled state
        self.setButtonsEnabled(False, "Killing...")
        
        # More specific kill command to avoid killing the GUI
        # Kill processes that have "meshtastic" in command line but exclude python processes
        cmd = "pkill -f '^meshtastic '"  # Only processes that start with 'meshtastic '
        
        # Execute the command in a separate thread
        self.kill_all_worker = CommandWorker(cmd)
        self.kill_all_worker.output_ready.connect(self.onCommandOutput)
        self.kill_all_worker.error_occurred.connect(self.onCommandError)
        self.kill_all_worker.finished.connect(self.onKillAllFinished)
        
        # Store timing info
        worker_id = id(self.kill_all_worker)
        self.command_start_times[worker_id] = command_start_time
        self.kill_all_worker.start()
        
        # Set a timer to re-enable buttons after 5 seconds
        from PyQt5.QtCore import QTimer
        self.kill_timer = QTimer()
        self.kill_timer.singleShot(5000, self.forceEnableButtons)  # 5 seconds
    
    def onKillAllFinished(self):
        """Handle kill CLI processes completion"""
        # Calculate execution time
        worker_id = id(self.kill_all_worker)
        execution_time = None
        if worker_id in self.command_start_times:
            execution_time = time.time() - self.command_start_times[worker_id]
            del self.command_start_times[worker_id]
        
        # Log completion with timing
        if execution_time:
            completion_msg = f"KILL ALL COMPLETED in {execution_time:.2f} seconds - CLI processes terminated"
        else:
            completion_msg = "KILL ALL COMPLETED - CLI processes terminated"
        
        self.results_display.append("\n" + "=" * 50 + "\n")
        self.logMessage(completion_msg, 'command')
        
        # Re-enable buttons immediately since CLI is cleared
        self.setButtonsEnabled(True)
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def setButtonsEnabled(self, enabled, kill_text="Kill All"):
        """Enable/disable all command buttons and set their text"""
        # Command buttons
        self.refresh_nodes_btn.setEnabled(enabled)
        self.traceroute_btn.setEnabled(enabled)
        self.telemetry_btn.setEnabled(enabled)
        self.send_msg_btn.setEnabled(enabled)
        self.reboot_btn.setEnabled(enabled if self.disconnect_btn.isEnabled() else False)  # Only if connected
        
        # Kill All button should ALWAYS be enabled (except during its own execution)
        self.kill_all_btn.setEnabled(kill_text != "Killing...")
        
        # Set appropriate text
        if enabled:
            self.refresh_nodes_btn.setText("Refresh Nodes")
            self.traceroute_btn.setText("Traceroute")
            self.telemetry_btn.setText("Get Telemetry")
            self.send_msg_btn.setText("Send Message")
            self.reboot_btn.setText("Reboot")
            self.kill_all_btn.setText(kill_text)
        else:
            # Show that operations are blocked
            if "Killing" not in kill_text:
                self.refresh_nodes_btn.setText("Wait...")
                self.traceroute_btn.setText("Wait...")
                self.telemetry_btn.setText("Wait...")
                self.send_msg_btn.setText("Wait...")
                self.reboot_btn.setText("Wait...")
            self.kill_all_btn.setText(kill_text)
    
    def forceEnableButtons(self):
        """Force re-enable all buttons after timeout"""
        self.setButtonsEnabled(True)
        self.logMessage("TIMEOUT: Buttons force re-enabled after 5 second timeout", 'system')
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onClearLog(self):
        """Clear the command results log"""
        reply = QMessageBox.question(
            self, "Clear Log",
            "Are you sure you want to clear the command results log?\n\n"
            "This will remove all command history and timestamps.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.results_display.clear()
            self.log_entries.clear()
            self.command_start_times.clear()
            
            # Add a clear log entry with timestamp
            current_time = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            clear_message = f"[{current_time}] Log cleared by user\n"
            self.results_display.append(clear_message)
            self.log_entries.append({
                'timestamp': current_time,
                'type': 'system',
                'message': 'Log cleared by user'
            })
    
    def getTimestamp(self):
        """Get current timestamp formatted for display"""
        return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    def logMessage(self, message, msg_type='info'):
        """Add a timestamped message to the log"""
        timestamp = self.getTimestamp()
        formatted_message = f"[{timestamp}] {message}"
        self.results_display.append(formatted_message)
        
        # Store for potential export
        self.log_entries.append({
            'timestamp': timestamp,
            'type': msg_type,
            'message': message
        })
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onLoadConfig(self):
        """Load device configuration using meshtastic --export-config command"""
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        if not address:
            QMessageBox.warning(self, "Warning", "Please connect to a device first.")
            return
        
        # Build command to get configuration only
        if method == "Serial Port":
            config_cmd = f'meshtastic --port {address} --export-config'
        elif method == "IP Address":
            config_cmd = f'meshtastic --host {address} --export-config'  
        else:  # Bluetooth
            config_cmd = f'meshtastic --ble {address} --export-config'
        
        self.results_display.append(f"Loading device configuration...\n")
        self.results_display.append(f"Command: {config_cmd}\n")
        self.results_display.append("=" * 50 + "\n")
        
        # Log command start with timestamp
        self.logMessage(f"CONFIG LOAD START: Getting configuration", 'command')
        command_start_time = time.time()
        
        # Disable buttons while loading
        self.load_config_btn.setEnabled(False)
        self.load_config_btn.setText("Loading...")
        
        # Initialize data storage
        self.current_config = {}
        self.current_device_info = {}
        self.config_output_lines = []
        
        # Store connection info for smart matching
        self.current_connection = {
            'method': method,
            'address': address,
            'preset': self.connection_preset.currentText() or f"{method}_{address}"
        }
        
        # Execute config command
        self.config_worker = CommandWorker(config_cmd)
        self.config_worker.output_ready.connect(self.onConfigLoadOutput)
        self.config_worker.error_occurred.connect(self.onCommandError)
        self.config_worker.finished.connect(self.onConfigCommandFinished)
        
        # Store timing info
        worker_id = id(self.config_worker)
        self.command_start_times[worker_id] = command_start_time
        self.config_worker.start()
    
    def onConfigLoadOutput(self, output):
        """Handle config command output"""
        # Add timestamped output
        timestamp = self.getTimestamp()
        self.results_display.append(f"[{timestamp}] CONFIG: {output}\n")
        
        # Store for log
        self.log_entries.append({
            'timestamp': timestamp,
            'type': 'output',
            'message': f"CONFIG: {output}"
        })
        
        # Check for common errors and provide helpful messages
        if "OS Error:" in output or "serial device couldn't be opened" in output:
            self.logMessage("WARNING: Device appears to be locked by another process", 'error')
        elif "Resource temporarily unavailable" in output:
            self.logMessage("TIP: Close any other meshtastic applications or web browsers using this device", 'info')
        elif "Could not exclusively lock port" in output:
            self.logMessage("TIP: Try disconnecting and reconnecting the device, or use 'Kill All' button", 'info')
        
        # Store config lines for parsing (skip error lines)
        if not ("OS Error:" in output or "serial device couldn't be opened" in output or "Resource temporarily unavailable" in output):
            self.config_output_lines.append(output)
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)

    def onInfoLoadOutput(self, output):
        """Handle info command output"""
        # Add timestamped output
        timestamp = self.getTimestamp()
        self.results_display.append(f"[{timestamp}] INFO: {output}\n")
        
        # Store for log
        self.log_entries.append({
            'timestamp': timestamp,
            'type': 'output',
            'message': f"INFO: {output}"
        })
        
        # Store info lines for parsing
        self.info_output_lines.append(output)
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onConfigCommandFinished(self):
        """Handle config command completion"""
        # Calculate execution time
        worker_id = id(self.config_worker)
        execution_time = None
        if worker_id in self.command_start_times:
            execution_time = time.time() - self.command_start_times[worker_id]
            del self.command_start_times[worker_id]
        
        # Log completion with timing
        if execution_time:
            completion_msg = f"CONFIG COMMAND COMPLETED in {execution_time:.2f} seconds"
        else:
            completion_msg = "CONFIG COMMAND COMPLETED"
        
        self.results_display.append("\n" + "=" * 50 + "\n")
        self.logMessage(completion_msg, 'command')
        
        # Parse the configuration output
        self.parseConfigOutput()
        
        # Re-enable buttons
        self.load_config_btn.setEnabled(True)
        self.load_config_btn.setText("Load Config")
        self.save_config_btn.setEnabled(True)
        self.reset_config_btn.setEnabled(True)
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
        
        # Show appropriate message based on results
        if hasattr(self, 'current_config') and self.current_config:
            device_name = self.current_config.get('owner', 'Unknown Device')
            QMessageBox.information(self, "Configuration Loaded", 
                                   f"Device configuration loaded successfully!\n\n"
                                   f"Device: {device_name}\n"
                                   f"Connection: {self.current_connection['preset']}\n"
                                   f"Method: {self.current_connection['method']} ({self.current_connection['address']})\n\n"
                                   f"Expand the configuration panel to view and edit settings.")
        elif any("OS Error:" in line or "serial device couldn't be opened" in line for line in self.config_output_lines):
            QMessageBox.warning(self, "Device Access Error", 
                               f"Cannot access the device - it may be in use by another application.\n\n"
                               f"Solutions:\n"
                               f"• Close any web browsers with meshtastic web interface open\n"
                               f"• Close other meshtastic CLI tools or applications\n"
                               f"• Disconnect and reconnect the USB cable\n"
                               f"• Use the 'Kill All' button to terminate other meshtastic processes\n\n"
                               f"Connection: {self.current_connection['method']} ({self.current_connection['address']})")
        elif len(self.config_output_lines) == 0:
            QMessageBox.warning(self, "No Configuration Data", 
                               "No configuration data received. Please check your connection and try again.\n\n"
                               "Make sure the device is properly connected and powered on.")
        else:
            QMessageBox.warning(self, "Configuration Parse Error", 
                               "Configuration data received but could not be parsed.\n\n"
                               "Check the log output for details about what was received.")
    
    def parseDeviceInfo(self):
        """Parse the meshtastic --info output"""
        try:
            info_text = '\n'.join(self.info_output_lines)
            
            # Parse key-value pairs from --info output
            for line in info_text.split('\n'):
                line = line.strip()
                if ':' in line and not line.startswith('#'):
                    key, value = line.split(':', 1)
                    key = key.strip().lower().replace(' ', '_').replace('-', '_')
                    value = value.strip()
                    
                    # Handle special cases
                    if key == 'my_node_num':
                        # Convert hex to !format
                        if value.startswith('0x'):
                            hex_val = value[2:]
                            self.current_device_info['node_id'] = f"!{hex_val}"
                        else:
                            self.current_device_info['node_id'] = value
                    
                    self.current_device_info[key] = value
            
            # Store device connection mapping for smart preset matching
            self.storeDeviceConnection()
            
        except Exception as e:
            QMessageBox.warning(self, "Info Parse Error", 
                               f"Failed to parse device info:\n{str(e)}")
    
    def storeDeviceConnection(self):
        """Store device connection info for smart preset matching"""
        if not hasattr(self, 'device_connections'):
            self.device_connections = {}
        
        # Get device identifier
        node_id = self.current_device_info.get('node_id', 'unknown')
        device_name = self.current_device_info.get('owner', 'Unknown Device')
        
        # Store connection info by device
        if node_id not in self.device_connections:
            self.device_connections[node_id] = {
                'device_name': device_name,
                'connections': {}
            }
        
        # Add this connection method
        connection_key = f"{self.current_connection['method']}_{self.current_connection['address']}"
        self.device_connections[node_id]['connections'][connection_key] = {
            'method': self.current_connection['method'],
            'address': self.current_connection['address'],
            'preset_name': self.current_connection['preset'],
            'last_used': datetime.datetime.now().isoformat(),
            'last_config': self.current_config.copy(),
            'last_info': self.current_device_info.copy()
        }
        
        # Save device connections
        self.saveDeviceConnections()
    
    def saveDeviceConnections(self):
        """Save device connection mappings to file"""
        try:
            with open('device_connections.json', 'w') as f:
                json.dump(self.device_connections, f, indent=2)
        except Exception:
            pass
    
    def loadDeviceConnections(self):
        """Load device connection mappings from file"""
        if os.path.exists('device_connections.json'):
            try:
                with open('device_connections.json', 'r') as f:
                    self.device_connections = json.load(f)
            except Exception:
                self.device_connections = {}
        else:
            self.device_connections = {}
    
    def buildConfigEditor(self):
        """Build the comprehensive configuration editor interface"""
        if not hasattr(self, 'current_config') or not self.current_config:
            return
        
        # Clear existing widgets
        for i in reversed(range(self.config_form_layout.count())):
            child = self.config_form_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        # Device Info Section (from --info)
        if hasattr(self, 'current_device_info') and self.current_device_info:
            self.buildDeviceInfoSection()
        
        # Configuration Sections (from --export-config)
        if 'config' in self.current_config:
            self.buildAdvancedConfigSection("Device Configuration", self.current_config['config'])
        
        if 'location' in self.current_config:
            self.buildAdvancedConfigSection("Location", self.current_config['location'])
        
        if 'module_config' in self.current_config:
            self.buildAdvancedConfigSection("Module Configuration", self.current_config['module_config'])
        
        # Connection Management Section
        self.buildConnectionManagementSection()
    
    def buildDeviceInfoSection(self):
        """Build device info section with key device details"""
        info_group = QGroupBox("📱 Device Information (Read-Only)")
        info_layout = QVBoxLayout()
        
        # Key device info in a nice grid
        grid_layout = QVBoxLayout()
        
        info_fields = [
            ('Device Name', self.current_device_info.get('owner', 'N/A')),
            ('Node ID', self.current_device_info.get('node_id', 'N/A')),
            ('Hardware', self.current_device_info.get('hardware', 'N/A')),
            ('Firmware Version', self.current_device_info.get('firmware_version', 'N/A')),
            ('MAC Address', self.current_device_info.get('macaddr', 'N/A')),
            ('Region', self.current_device_info.get('region', 'N/A')),
        ]
        
        for label, value in info_fields:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{label}:"))
            
            # Make values selectable but read-only
            value_field = QLineEdit(str(value))
            value_field.setReadOnly(True)
            value_field.setMaximumWidth(200)
            value_field.setStyleSheet("QLineEdit { background-color: #f5f5f5; }")
            
            row.addWidget(value_field)
            row.addStretch()
            grid_layout.addLayout(row)
        
        info_layout.addLayout(grid_layout)
        info_group.setLayout(info_layout)
        self.config_form_layout.addWidget(info_group)
    
    def buildAdvancedConfigSection(self, section_name, config_data):
        """Build an advanced collapsible section for configuration data with proper input types"""
        if not isinstance(config_data, dict):
            return
        
        section_group = QGroupBox(f"⚙️ {section_name}")
        section_layout = QVBoxLayout()
        
        # Sort keys for consistent ordering
        for key in sorted(config_data.keys()):
            value = config_data[key]
            
            if isinstance(value, dict):
                # Nested section - create sub-group
                self.buildNestedAdvancedSection(section_layout, key, value, f"{section_name}_{key}")
            else:
                # Simple key-value pair with proper input widget
                row = QHBoxLayout()
                
                # Create label with tooltip if available
                label = QLabel(f"{key.replace('_', ' ').title()}:")
                label.setMinimumWidth(150)
                row.addWidget(label)
                
                # Create appropriate input widget based on value type and common patterns
                widget = self.createConfigWidget(key, value, f"{section_name}_{key}")
                row.addWidget(widget)
                row.addStretch()
                section_layout.addLayout(row)
        
        section_group.setLayout(section_layout)
        self.config_form_layout.addWidget(section_group)
    
    def buildNestedAdvancedSection(self, parent_layout, section_name, config_data, full_path):
        """Build a nested configuration section with proper grouping"""
        nested_group = QGroupBox(f"📂 {section_name.replace('_', ' ').title()}")
        nested_layout = QVBoxLayout()
        
        # Sort keys for consistent ordering
        for key in sorted(config_data.keys()):
            value = config_data[key]
            
            if isinstance(value, dict):
                # Further nested - create another sub-group
                self.buildNestedAdvancedSection(nested_layout, key, value, f"{full_path}_{key}")
            else:
                # Simple key-value pair
                row = QHBoxLayout()
                
                label = QLabel(f"{key.replace('_', ' ').title()}:")
                label.setMinimumWidth(120)
                row.addWidget(label)
                
                # Create appropriate input widget
                widget = self.createConfigWidget(key, value, f"{full_path}_{key}")
                row.addWidget(widget)
                row.addStretch()
                nested_layout.addLayout(row)
        
        nested_group.setLayout(nested_layout)
        parent_layout.addWidget(nested_group)
    
    def createConfigWidget(self, key, value, full_path):
        """Create the appropriate widget for a configuration value"""
        from PyQt5.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox
        
        key_lower = key.lower()
        
        # Boolean values
        if isinstance(value, bool):
            widget = QCheckBox()
            widget.setChecked(value)
            widget.setObjectName(f"config_{full_path}")
            return widget
        
        # Integer values with known ranges
        elif isinstance(value, int):
            if 'port' in key_lower or 'pin' in key_lower:
                # Port/Pin numbers
                widget = QSpinBox()
                widget.setRange(0, 65535)
                widget.setValue(value)
            elif 'power' in key_lower or 'tx' in key_lower and 'power' in key_lower:
                # TX Power
                widget = QSpinBox()
                widget.setRange(0, 30)
                widget.setValue(value)
            elif 'hop' in key_lower:
                # Hop limit
                widget = QSpinBox()
                widget.setRange(1, 7)
                widget.setValue(value)
            elif 'channel' in key_lower or 'ch' in key_lower:
                # Channel numbers
                widget = QSpinBox()
                widget.setRange(0, 255)
                widget.setValue(value)
            elif 'interval' in key_lower or 'secs' in key_lower or 'seconds' in key_lower:
                # Time intervals
                widget = QSpinBox()
                widget.setRange(0, 4294967295)  # Max uint32
                widget.setValue(value)
            else:
                # Generic integer
                widget = QSpinBox()
                widget.setRange(-2147483648, 2147483647)
                widget.setValue(value)
            
            widget.setObjectName(f"config_{full_path}")
            return widget
        
        # Float values
        elif isinstance(value, float):
            widget = QDoubleSpinBox()
            widget.setRange(-999999.0, 999999.0)
            widget.setDecimals(6)
            widget.setValue(value)
            widget.setObjectName(f"config_{full_path}")
            return widget
        
        # String values with known enums
        elif isinstance(value, str):
            if 'region' in key_lower:
                # LoRa regions
                widget = QComboBox()
                widget.addItems(['US', 'EU_868', 'EU_433', 'CN', 'JP', 'ANZ', 'KR', 'TW', 'RU', 'IN', 'NZ_865', 'TH', 'UA_868', 'UA_433', 'MY_919', 'MY_433', 'SG_923'])
                widget.setCurrentText(value)
            elif 'mode' in key_lower:
                # Various mode options
                if 'gps' in key_lower:
                    widget = QComboBox()
                    widget.addItems(['DISABLED', 'ENABLED', 'NOT_PRESENT'])
                elif 'bluetooth' in key_lower or 'bt' in key_lower:
                    widget = QComboBox()
                    widget.addItems(['RANDOM_PIN', 'FIXED_PIN', 'NO_PIN'])
                else:
                    widget = QLineEdit(str(value))
                widget.setCurrentText(value) if hasattr(widget, 'setCurrentText') else widget.setText(str(value))
            elif key_lower in ['address', 'server', 'host', 'url', 'root', 'username', 'password']:
                # Network/connection strings
                widget = QLineEdit(str(value))
                widget.setMaximumWidth(300)
            elif 'key' in key_lower and len(str(value)) > 20:
                # Cryptographic keys - make read-only and show truncated
                widget = QLineEdit(str(value)[:20] + "..." if len(str(value)) > 20 else str(value))
                widget.setReadOnly(True)
                widget.setMaximumWidth(200)
                widget.setStyleSheet("QLineEdit { background-color: #fff3cd; }")  # Light yellow
            else:
                # Generic string
                widget = QLineEdit(str(value))
                widget.setMaximumWidth(200)
            
            widget.setObjectName(f"config_{full_path}")
            return widget
        
        # Default case
        else:
            widget = QLineEdit(str(value))
            widget.setMaximumWidth(200)
            widget.setObjectName(f"config_{full_path}")
            return widget
    
    def buildConnectionManagementSection(self):
        """Build connection management section showing all ways to reach this device"""
        if not hasattr(self, 'current_device_info') or not self.current_device_info:
            return
        
        node_id = self.current_device_info.get('node_id', 'unknown')
        device_name = self.current_device_info.get('owner', 'Unknown Device')
        
        conn_group = QGroupBox(f"🔗 Connection Management - {device_name}")
        conn_layout = QVBoxLayout()
        
        # Current connection info
        current_row = QHBoxLayout()
        current_row.addWidget(QLabel("Current Connection:"))
        current_info = f"{self.current_connection['method']} ({self.current_connection['address']})"
        current_field = QLineEdit(current_info)
        current_field.setReadOnly(True)
        current_field.setMaximumWidth(300)
        current_field.setStyleSheet("QLineEdit { background-color: #d4edda; }")  # Light green
        current_row.addWidget(current_field)
        current_row.addStretch()
        conn_layout.addLayout(current_row)
        
        # Show all known connections for this device
        if hasattr(self, 'device_connections') and node_id in self.device_connections:
            conn_layout.addWidget(QLabel("All Known Connections:"))
            
            for conn_key, conn_info in self.device_connections[node_id]['connections'].items():
                conn_row = QHBoxLayout()
                
                # Connection method and address
                conn_text = f"{conn_info['method']}: {conn_info['address']}"
                conn_field = QLineEdit(conn_text)
                conn_field.setReadOnly(True)
                conn_field.setMaximumWidth(250)
                conn_row.addWidget(conn_field)
                
                # Last used
                try:
                    last_used = datetime.datetime.fromisoformat(conn_info['last_used'])
                    last_used_str = last_used.strftime("%Y-%m-%d %H:%M")
                except:
                    last_used_str = "Unknown"
                
                last_used_field = QLineEdit(f"Last used: {last_used_str}")
                last_used_field.setReadOnly(True)
                last_used_field.setMaximumWidth(150)
                last_used_field.setStyleSheet("QLineEdit { background-color: #f8f9fa; }")
                conn_row.addWidget(last_used_field)
                
                # Quick connect button
                if conn_key != f"{self.current_connection['method']}_{self.current_connection['address']}":
                    switch_btn = QPushButton("Switch")
                    switch_btn.setMaximumWidth(60)
                    switch_btn.clicked.connect(lambda checked, c=conn_info: self.switchConnection(c))
                    conn_row.addWidget(switch_btn)
                else:
                    active_label = QLabel("(Active)")
                    active_label.setStyleSheet("QLabel { color: green; font-weight: bold; }")
                    conn_row.addWidget(active_label)
                
                conn_row.addStretch()
                conn_layout.addLayout(conn_row)
        
        conn_group.setLayout(conn_layout)
        self.config_form_layout.addWidget(conn_group)
    
    def switchConnection(self, conn_info):
        """Switch to a different connection method for the same device"""
        reply = QMessageBox.question(
            self, "Switch Connection",
            f"Switch to {conn_info['method']} connection at {conn_info['address']}?\n\n"
            f"This will update the connection settings and reload the configuration.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Update connection settings
            method_index = self.connection_method.findText(conn_info['method'])
            if method_index >= 0:
                self.connection_method.setCurrentIndex(method_index)
            
            self.connection_input.setText(conn_info['address'])
            
            # Reload configuration
            QMessageBox.information(self, "Connection Switched", 
                                   f"Connection switched to {conn_info['method']}.\n"
                                   f"Click 'Load Config' to refresh the configuration.")
    
    def onToggleConfigVisibility(self):
        """Toggle the visibility of the configuration editor"""
        is_visible = self.config_scroll.isVisible()
        
        if is_visible:
            self.config_scroll.setVisible(False)
            self.toggle_config_btn.setText("▶ Show Configuration")
        else:
            self.config_scroll.setVisible(True)
            self.toggle_config_btn.setText("▼ Hide Configuration")
    
    def onSaveConfig(self):
        """Save modified configuration back to device"""
        if not hasattr(self, 'current_config') or not self.current_config:
            QMessageBox.warning(self, "Warning", "No configuration loaded. Please load configuration first.")
            return
        
        # TODO: Implement config saving
        QMessageBox.information(self, "Save Configuration", "Configuration saving will be implemented in next update.")
    
    def onResetConfig(self):
        """Reset configuration to loaded state"""
        if not hasattr(self, 'current_config') or not self.current_config:
            QMessageBox.warning(self, "Warning", "No configuration loaded. Please load configuration first.")
            return
        
        reply = QMessageBox.question(
            self, "Reset Configuration",
            "This will reset all configuration changes to the last loaded state.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.buildConfigEditor()
            QMessageBox.information(self, "Configuration Reset", "Configuration has been reset to loaded state.")
    
    def parseConfigOutput(self):
        """Parse the meshtastic --export-config output (YAML format)"""
        try:
            import yaml
            
            # Join all config output lines
            config_text = '\n'.join(self.config_output_lines)
            
            if not config_text.strip():
                self.logMessage("ERROR: No configuration data received", 'error')
                return
            
            # Remove any error messages or non-YAML content from the beginning
            lines = config_text.split('\n')
            yaml_lines = []
            yaml_started = False
            
            for line in lines:
                # Skip error lines
                if 'OS Error:' in line or 'serial device couldn\'t be opened' in line or 'Resource temporarily unavailable' in line:
                    continue
                # Look for the start of YAML content
                if line.strip().startswith('owner:') or line.strip().startswith('config:') or line.strip().startswith('# start of Meshtastic configure yaml') or yaml_started:
                    yaml_started = True
                    yaml_lines.append(line)
                elif yaml_started:
                    yaml_lines.append(line)
            
            if not yaml_lines:
                self.logMessage("ERROR: No YAML configuration found in output", 'error')
                return
            
            clean_yaml = '\n'.join(yaml_lines)
            self.logMessage(f"Parsing YAML configuration ({len(yaml_lines)} lines)", 'info')
            
            # Parse the YAML
            self.current_config = yaml.safe_load(clean_yaml)
            
            if not self.current_config:
                self.logMessage("ERROR: YAML parsing returned empty configuration", 'error')
                return
            
            self.logMessage(f"Successfully parsed configuration with {len(self.current_config)} sections", 'info')
            
            # Extract basic device info from config if available
            if 'owner' in self.current_config:
                self.current_device_info['owner'] = self.current_config['owner']
            
            # Handle flat structure - the YAML is parsed as flat keys instead of nested
            # Look for role in the flat structure
            if 'role' in self.current_config:
                self.current_device_info['role'] = self.current_config['role']
            
            # Store device connection mapping
            self.storeDeviceConnection()
            
            # Build the configuration editor
            self.buildConfigEditor()
            
        except ImportError:
            self.logMessage("ERROR: PyYAML not installed. Please install it: pip install pyyaml", 'error')
            QMessageBox.critical(self, "Missing Dependency", 
                               "PyYAML is required to parse meshtastic configuration.\n\n"
                               "Please install it with: pip install pyyaml")
        except yaml.YAMLError as e:
            self.logMessage(f"YAML Parse Error: {str(e)}", 'error')
            QMessageBox.warning(self, "Configuration Parse Error", 
                               f"Failed to parse YAML configuration:\n{str(e)}\n\n"
                               "Check the log output for the raw configuration data.")
        except Exception as e:
            self.logMessage(f"Configuration Parse Error: {str(e)}", 'error')
            QMessageBox.warning(self, "Configuration Parse Error", 
                               f"Failed to parse configuration:\n{str(e)}")
    
    def storeDeviceConnection(self):
        """Store device connection info for smart preset matching"""
        if not hasattr(self, 'device_connections'):
            self.device_connections = {}
        
        # Get device identifier from config
        device_name = self.current_config.get('owner', 'Unknown Device')
        
        # Generate a simple node_id if we don't have one from --info
        node_id = self.current_device_info.get('node_id', f"device_{device_name.replace(' ', '_')}")
        
        # Store connection info by device
        if node_id not in self.device_connections:
            self.device_connections[node_id] = {
                'device_name': device_name,
                'connections': {}
            }
        
        # Add this connection method
        connection_key = f"{self.current_connection['method']}_{self.current_connection['address']}"
        self.device_connections[node_id]['connections'][connection_key] = {
            'method': self.current_connection['method'],
            'address': self.current_connection['address'],
            'preset_name': self.current_connection['preset'],
            'last_used': datetime.datetime.now().isoformat(),
            'last_config': self.current_config.copy() if self.current_config else {},
            'last_info': self.current_device_info.copy() if self.current_device_info else {}
        }
        
        # Save device connections
        self.saveDeviceConnections()
    
    def buildConfigEditor(self):
        """Build the configuration editor interface for flat YAML structure"""
        if not hasattr(self, 'current_config') or not self.current_config:
            return
        
        # Clear existing widgets
        for i in reversed(range(self.config_form_layout.count())):
            child = self.config_form_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        # Group the flat config into logical sections
        config_groups = {
            'Owner Information': ['owner', 'owner_short', 'channel_url'],
            'Device Settings': ['disableTripleClick', 'ledHeartbeatDisabled', 'nodeInfoBroadcastSecs', 'tzdef'],
            'Bluetooth': ['enabled', 'fixedPin', 'mode'],
            'Display': ['screenOnSecs'],
            'LoRa Radio': ['configOkToMqtt', 'hopLimit', 'region', 'sx126xRxBoostedGain', 'txEnabled', 'txPower', 'usePreset'],
            'Network': ['ntpServer'],
            'Position/GPS': ['broadcastSmartMinimumDistance', 'broadcastSmartMinimumIntervalSecs', 'gpsMode', 'gpsUpdateInterval', 'positionBroadcastSecs', 'positionBroadcastSmartEnabled', 'positionFlags'],
            'Power Management': ['lsSecs', 'minWakeSecs', 'sdsSecs', 'waitBluetoothSecs'],
            'Security': ['privateKey', 'publicKey', 'serialEnabled'],
            'Location': ['alt', 'lat', 'lon'],
            'Ambient Lighting': ['blue', 'current', 'green', 'red'],
            'Detection Sensor': ['detectionTriggerType', 'minimumBroadcastSecs'],
            'MQTT': ['address', 'encryptionEnabled', 'mapReportingEnabled', 'password', 'root', 'username'],
            'Range Test': ['sender'],
            'Serial': ['enabled'],
            'Telemetry': ['deviceUpdateInterval']
        }
        
        # Build sections
        for section_name, keys in config_groups.items():
            section_data = {}
            for key in keys:
                if key in self.current_config:
                    section_data[key] = self.current_config[key]
            
            if section_data:  # Only create section if it has data
                self.buildFlatConfigSection(section_name, section_data)
        
        # Add any remaining keys that weren't grouped
        remaining_keys = set(self.current_config.keys()) - set().union(*config_groups.values())
        if remaining_keys:
            remaining_data = {key: self.current_config[key] for key in remaining_keys}
            self.buildFlatConfigSection("Other Settings", remaining_data)
    
    def buildFlatConfigSection(self, section_name, config_data):
        """Build a section for flat configuration data"""
        if not config_data:
            return
        
        section_group = QGroupBox(section_name)
        section_layout = QVBoxLayout()
        
        for key, value in config_data.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{key}:"))
            
            # Create appropriate input widget based on value type
            if isinstance(value, bool):
                widget = QCheckBox()
                widget.setChecked(value)
                widget.stateChanged.connect(lambda state, k=key: self.updateConfigValue(k, state == 2))  # 2 is checked state
            elif isinstance(value, int):
                widget = QSpinBox()
                widget.setRange(-999999, 999999)
                widget.setValue(value)
                widget.valueChanged.connect(lambda val, k=key: self.updateConfigValue(k, val))
            elif isinstance(value, float):
                widget = QDoubleSpinBox()
                widget.setRange(-999999.0, 999999.0)
                widget.setValue(value)
                widget.valueChanged.connect(lambda val, k=key: self.updateConfigValue(k, val))
            elif isinstance(value, str):
                widget = QLineEdit(str(value))
                widget.textChanged.connect(lambda text, k=key: self.updateConfigValue(k, text))
                if key in ['privateKey', 'publicKey', 'password']:
                    widget.setEchoMode(QLineEdit.Password)
            else:
                # For any other type, use a line edit with string representation
                widget = QLineEdit(str(value))
                widget.textChanged.connect(lambda text, k=key: self.updateConfigValue(k, text))
            
            row.addWidget(widget)
            
            # Add value type indicator
            type_label = QLabel(f"({type(value).__name__})")
            type_label.setStyleSheet("color: #666666; font-size: 10px;")
            row.addWidget(type_label)
            
            section_layout.addLayout(row)
        
        section_group.setLayout(section_layout)
        self.config_form_layout.addWidget(section_group)
        
    def updateConfigValue(self, key, value):
        """Update configuration value when user modifies input"""
        if hasattr(self, 'current_config') and self.current_config:
            self.current_config[key] = value
            print(f"Updated config: {key} = {value}")

    def buildConfigSection(self, section_name, config_data):
        """Build a collapsible section for configuration data"""
        if not isinstance(config_data, dict):
            return
        
        section_group = QGroupBox(section_name)
        section_layout = QVBoxLayout()
        
        for key, value in config_data.items():
            if isinstance(value, dict):
                # Nested section
                self.buildNestedSection(section_layout, key, value)
            else:
                # Simple key-value pair
                row = QHBoxLayout()
                row.addWidget(QLabel(f"{key}:"))
                
                # Create appropriate input widget based on value type
                if isinstance(value, bool):
                    widget = QCheckBox()
                    widget.setChecked(value)
                elif isinstance(value, (int, float)):
                    widget = QLineEdit(str(value))
                    widget.setMaximumWidth(100)
                else:
                    widget = QLineEdit(str(value))
                    widget.setMaximumWidth(200)
                
                widget.setObjectName(f"config_{section_name}_{key}")
                row.addWidget(widget)
                row.addStretch()
                section_layout.addLayout(row)
        
        section_group.setLayout(section_layout)
        self.config_form_layout.addWidget(section_group)
    
    def buildNestedSection(self, parent_layout, section_name, config_data):
        """Build a nested configuration section"""
        nested_group = QGroupBox(section_name.title())
        nested_layout = QVBoxLayout()
        
        for key, value in config_data.items():
            if isinstance(value, dict):
                # Further nested - just show as text for now
                nested_layout.addWidget(QLabel(f"{key}: {str(value)}"))
            else:
                # Simple key-value pair
                row = QHBoxLayout()
                row.addWidget(QLabel(f"{key}:"))
                
                # Create appropriate input widget
                if isinstance(value, bool):
                    widget = QCheckBox()
                    widget.setChecked(value)
                elif isinstance(value, (int, float)):
                    widget = QLineEdit(str(value))
                    widget.setMaximumWidth(100)
                else:
                    widget = QLineEdit(str(value))
                    widget.setMaximumWidth(200)
                
                widget.setObjectName(f"config_{section_name}_{key}")
                row.addWidget(widget)
                row.addStretch()
                nested_layout.addLayout(row)
        
        nested_group.setLayout(nested_layout)
        parent_layout.addWidget(nested_group)

    def onTraceroute(self):
        target = self.target_select.currentText()
        if not target:
            QMessageBox.warning(self, "Warning", "Please select a target for traceroute.")
            return
        
        # Extract ID from target text (handle favorite star prefix)
        if target.startswith("★ "):
            # Format: "★ !node_id (aka)" - get the second part
            target_id = target.split(' ')[1]
        else:
            # Format: "!node_id (aka)" or "!node_id (aka) [Manual]" - get the first part
            target_id = target.split(' ')[0]
        channel = self.channel_input.value()
        
        # Build command based on connection method
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        if method == "Serial Port":
            cmd = f'meshtastic --port {address} --traceroute "{target_id}" --ch-index {channel}'
        elif method == "IP Address":
            cmd = f'meshtastic --host {address} --traceroute "{target_id}" --ch-index {channel}'
        else:  # Bluetooth
            cmd = f'meshtastic --ble {address} --traceroute "{target_id}" --ch-index {channel}'
        
        self.results_display.append(f"Running: {cmd}\n")
        self.results_display.append("=" * 50 + "\n")
        
        # Log command start with timestamp
        self.logMessage(f"COMMAND START: {cmd}", 'command')
        command_start_time = time.time()
        
        # Disable all command buttons while traceroute is running
        self.setButtonsEnabled(False, "Kill All")
        self.traceroute_btn.setText("Running...")
        
        # Execute the command in a separate thread
        self.command_worker = CommandWorker(cmd)
        self.command_worker.output_ready.connect(self.onCommandOutput)
        self.command_worker.error_occurred.connect(self.onCommandError)
        self.command_worker.finished.connect(self.onCommandFinished)
        
        # Store traceroute context for processing results
        self.current_traceroute = {
            'target_id': target_id,
            'channel': channel,
            'timestamp': None,
            'route': [],
            'success': False,
            'from_node': None  # Will be determined from connection
        }
        
        # Store timing info
        worker_id = id(self.command_worker)
        self.command_start_times[worker_id] = command_start_time
        self.command_worker.start()
    
    def onRequestTelemetry(self):
        target = self.target_select.currentText()
        if not target:
            QMessageBox.warning(self, "Warning", "Please select a target for telemetry request.")
            return
        
        # Extract ID from target text (handle favorite star prefix)
        if target.startswith("★ "):
            # Format: "★ !node_id (aka)" - get the second part
            target_id = target.split(' ')[1]
        else:
            # Format: "!node_id (aka)" or "!node_id (aka) [Manual]" - get the first part
            target_id = target.split(' ')[0]
        
        # Build command based on connection method
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        if method == "Serial Port":
            cmd = f'meshtastic --port {address} --request-telemetry --dest "{target_id}"'
        elif method == "IP Address":
            cmd = f'meshtastic --host {address} --request-telemetry --dest "{target_id}"'
        else:  # Bluetooth
            cmd = f'meshtastic --ble {address} --request-telemetry --dest "{target_id}"'
        
        self.results_display.append(f"Requesting telemetry: {cmd}\n")
        self.results_display.append("=" * 50 + "\n")
        
        # Log command start with timestamp
        self.logMessage(f"TELEMETRY START: {cmd}", 'command')
        command_start_time = time.time()
        
        # Disable all command buttons while telemetry request is running
        self.setButtonsEnabled(False, "Kill All")
        self.telemetry_btn.setText("Requesting...")
        
        # Execute the command in a separate thread
        self.telemetry_worker = CommandWorker(cmd)
        self.telemetry_worker.output_ready.connect(self.onCommandOutput)
        self.telemetry_worker.error_occurred.connect(self.onCommandError)
        self.telemetry_worker.finished.connect(self.onTelemetryFinished)
        
        # Store telemetry context for processing results
        self.current_telemetry = {
            'target_id': target_id,
            'timestamp': None,
            'telemetry_data': {},
            'success': False,
            'from_node': 'local'  # Will be determined from connection
        }
        
        # Store timing info
        worker_id = id(self.telemetry_worker)
        self.command_start_times[worker_id] = command_start_time
        self.telemetry_worker.start()
    
    def onMessageTypeChanged(self, message_type):
        """Handle message type change"""
        if message_type == "To Channel":
            # When sending to channel, ACK is not applicable
            self.ack_cb.setEnabled(False)
            self.ack_cb.setChecked(False)
            self.ack_cb.setToolTip("ACK is not available for channel messages")
        else:  # "To Node"
            # When sending to node, ACK can be requested
            self.ack_cb.setEnabled(True)
            self.ack_cb.setToolTip("Request acknowledgment when sending to a specific node")
    
    def onSendMessage(self):
        """Send a text message either to channel or specific node"""
        message_text = self.message_input.text().strip()
        if not message_text:
            QMessageBox.warning(self, "Warning", "Please enter a message to send.")
            return
        
        message_type = self.message_type.currentText()
        channel = self.channel_input.value()
        
        # Build command based on connection method
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        if not address:
            QMessageBox.warning(self, "Warning", "Please connect to a device first.")
            return
        
        # Base command parts
        if method == "Serial Port":
            base_cmd = f'meshtastic --port {address}'
        elif method == "IP Address":
            base_cmd = f'meshtastic --host {address}'
        else:  # Bluetooth
            base_cmd = f'meshtastic --ble {address}'
        
        if message_type == "To Channel":
            # Send to channel (broadcast)
            cmd = f'{base_cmd} --ch-index {channel} --sendtext "{message_text}"'
            display_target = f"Channel {channel}"
        else:  # "To Node"
            # Send to specific node
            target = self.target_select.currentText()
            if not target:
                QMessageBox.warning(self, "Warning", "Please select a target node for direct message.")
                return
            
            # Extract ID from target text (handle favorite star prefix)
            if target.startswith("★ "):
                # Format: "★ !node_id (aka)" - get the second part
                target_id = target.split(' ')[1]
            else:
                # Format: "!node_id (aka)" or "!node_id (aka) [Manual]" - get the first part
                target_id = target.split(' ')[0]
            
            # Build node-specific command
            cmd = f'{base_cmd} --sendtext "{message_text}" --dest "{target_id}"'
            if self.ack_cb.isChecked():
                cmd += " --ack"
            
            display_target = f"Node {target_id}"
        
        self.results_display.append(f"Sending message to {display_target}: {cmd}\n")
        self.results_display.append("=" * 50 + "\n")
        
        # Log command start with timestamp
        self.logMessage(f"MESSAGE START: {cmd}", 'command')
        command_start_time = time.time()
        
        # Disable all command buttons while message is being sent
        self.setButtonsEnabled(False, "Kill All")
        self.send_msg_btn.setText("Sending...")
        
        # Execute the command in a separate thread
        self.message_worker = CommandWorker(cmd)
        self.message_worker.output_ready.connect(self.onCommandOutput)
        self.message_worker.error_occurred.connect(self.onCommandError)
        self.message_worker.finished.connect(self.onMessageFinished)
        
        # Store timing info
        worker_id = id(self.message_worker)
        self.command_start_times[worker_id] = command_start_time
        self.message_worker.start()
    
    def onMessageFinished(self):
        """Handle message send completion"""
        # Calculate execution time
        worker_id = id(self.message_worker)
        execution_time = None
        if worker_id in self.command_start_times:
            execution_time = time.time() - self.command_start_times[worker_id]
            del self.command_start_times[worker_id]
        
        # Log completion with timing
        if execution_time:
            completion_msg = f"MESSAGE SENT in {execution_time:.2f} seconds"
        else:
            completion_msg = "MESSAGE SENT"
        
        self.results_display.append("\n" + "=" * 50 + "\n")
        self.logMessage(completion_msg, 'command')
        
        # Re-enable all buttons
        self.setButtonsEnabled(True)
        
        # Clear message input for next message
        self.message_input.clear()
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onRebootFinished(self):
        """Handle reboot command completion"""
        # Calculate execution time
        worker_id = id(self.reboot_worker)
        execution_time = None
        if worker_id in self.command_start_times:
            execution_time = time.time() - self.command_start_times[worker_id]
            del self.command_start_times[worker_id]
        
        # Log completion with timing
        if execution_time:
            completion_msg = f"REBOOT SENT in {execution_time:.2f} seconds - Device will restart"
        else:
            completion_msg = "REBOOT SENT - Device will restart"
        
        self.results_display.append("\n" + "=" * 50 + "\n")
        self.logMessage(completion_msg, 'command')
        
        # Re-enable all buttons
        self.setButtonsEnabled(True)
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onCommandOutput(self, output):
        """Handle command output"""
        # Add timestamped output
        timestamp = self.getTimestamp()
        self.results_display.append(f"[{timestamp}] {output}\n")
        
        # Store for log
        self.log_entries.append({
            'timestamp': timestamp,
            'type': 'output',
            'message': output
        })
        
        # Parse traceroute-specific output
        if hasattr(self, 'current_traceroute') and self.current_traceroute:
            self.parseTracerouteOutput(output)
        
        # Parse telemetry-specific output
        if hasattr(self, 'current_telemetry') and self.current_telemetry:
            self.parseTelemetryOutput(output)
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onCommandError(self, error):
        """Handle command error"""
        timestamp = self.getTimestamp()
        self.results_display.append(f"[{timestamp}] ERROR: {error}\n")
        
        # Store error for log
        self.log_entries.append({
            'timestamp': timestamp,
            'type': 'error',
            'message': f"ERROR: {error}"
        })
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onCommandFinished(self):
        """Handle command completion"""
        # Calculate execution time
        worker_id = id(self.command_worker)
        execution_time = None
        if worker_id in self.command_start_times:
            execution_time = time.time() - self.command_start_times[worker_id]
            del self.command_start_times[worker_id]
        
        # Log completion with timing
        timestamp = self.getTimestamp()
        if execution_time:
            completion_msg = f"COMMAND COMPLETED in {execution_time:.2f} seconds"
        else:
            completion_msg = "COMMAND COMPLETED"
        
        self.results_display.append("\n" + "=" * 50 + "\n")
        self.logMessage(completion_msg, 'command')
        
        # Save traceroute results if we have them
        if hasattr(self, 'current_traceroute') and self.current_traceroute and self.current_traceroute.get('timestamp'):
            self.saveTracerouteResult()
        
        # Re-enable all buttons
        self.setButtonsEnabled(True)
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onTelemetryFinished(self):
        """Handle telemetry command completion"""
        # Calculate execution time
        worker_id = id(self.telemetry_worker)
        execution_time = None
        if worker_id in self.command_start_times:
            execution_time = time.time() - self.command_start_times[worker_id]
            del self.command_start_times[worker_id]
        
        # Log completion with timing
        timestamp = self.getTimestamp()
        if execution_time:
            completion_msg = f"TELEMETRY COMPLETED in {execution_time:.2f} seconds"
        else:
            completion_msg = "TELEMETRY COMPLETED"
        
        self.results_display.append("\n" + "=" * 50 + "\n")
        self.logMessage(completion_msg, 'command')
        
        # Save telemetry results if we have them
        if hasattr(self, 'current_telemetry') and self.current_telemetry and self.current_telemetry.get('timestamp'):
            self.saveTelemetryResult()
        
        # Re-enable all buttons
        self.setButtonsEnabled(True)
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onRefreshNodes(self):
        """Refresh the node list from meshtastic"""
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        if not address:
            QMessageBox.warning(self, "Warning", "Please connect to a device first.")
            return
        
        # Build command to get node list
        if method == "Serial Port":
            cmd = f'meshtastic --port {address} --nodes'
        elif method == "IP Address":
            cmd = f'meshtastic --host {address} --nodes'
        else:  # Bluetooth
            cmd = f'meshtastic --ble {address} --nodes'
        
        self.results_display.append(f"Refreshing nodes: {cmd}\n")
        self.results_display.append("=" * 30 + "\n")
        
        # FIXED: Clear the table at start of refresh to avoid stale data
        self.nodes_table.setRowCount(0)
        
        # Log command start with timestamp
        self.logMessage(f"REFRESH START: {cmd}", 'command')
        command_start_time = time.time()
        
        # Disable all command buttons while refresh is running
        self.setButtonsEnabled(False, "Kill All")
        self.refresh_nodes_btn.setText("Refreshing...")
        
        # Execute the command in a separate thread
        self.refresh_worker = CommandWorker(cmd)
        self.refresh_worker.output_ready.connect(self.onRefreshOutput)
        self.refresh_worker.error_occurred.connect(self.onCommandError)
        self.refresh_worker.finished.connect(self.onRefreshFinished)
        
        # Store timing info
        worker_id = id(self.refresh_worker)
        self.command_start_times[worker_id] = command_start_time
        self.refresh_worker.start()
    
    def onRefreshOutput(self, output):
        """Handle refresh command output"""
        # Add timestamped output
        timestamp = self.getTimestamp()
        self.results_display.append(f"[{timestamp}] {output}\n")
        
        # Store for log
        self.log_entries.append({
            'timestamp': timestamp,
            'type': 'output',
            'message': output
        })
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
        
        # Parse the node output if it contains node data
        if "│" in output and "│" in output and not output.startswith("╒") and not output.startswith("╞") and not output.startswith("├") and not output.startswith("╘"):
            self.parseNodeLine(output)
    
    def parseNodeLine(self, output):
        """Parse a node line from meshtastic --nodes output"""
        import datetime
        try:
            # Skip header lines and separators
            if (output.startswith("╒") or output.startswith("╞") or 
                output.startswith("├") or output.startswith("╘") or
                output.startswith("│   N │ User") or
                "═══════" in output):
                return
                
            # Split the line by │ separator and clean up
            parts = [part.strip() for part in output.split("│")]
            
            if len(parts) >= 8:  # Minimum expected columns
                row_num = parts[1] if len(parts) > 1 else ""
                user = parts[2] if len(parts) > 2 else ""
                node_id = parts[3] if len(parts) > 3 else ""
                aka = parts[4] if len(parts) > 4 else ""
                hardware = parts[5] if len(parts) > 5 else ""
                
                # Skip if this is a header row or invalid data
                if (not node_id or node_id == "ID" or not node_id.startswith("!") or
                    row_num == "N" or user == "User"):
                    return
                
                # Get current connection preset info
                current_preset = self.connection_preset.currentText() or "Default"
                current_method = self.connection_method.currentText()
                current_address = self.connection_input.text().strip()
                current_timestamp = datetime.datetime.now().isoformat()
                
                # Create or update node data
                if node_id not in self.discovered_nodes:
                    self.discovered_nodes[node_id] = {}
                
                node_data = self.discovered_nodes[node_id]
                node_data['user'] = user
                node_data['aka'] = aka
                node_data['hardware'] = hardware
                
                # Add connection preset tracking
                node_data['source_preset'] = current_preset
                node_data['source_method'] = current_method
                node_data['source_address'] = current_address
                node_data['last_updated'] = current_timestamp
                
                # Only set discovery_timestamp if this is a new node
                if 'discovery_timestamp' not in node_data:
                    node_data['discovery_timestamp'] = current_timestamp
                
                # Parse additional columns (pubkey, role, lat, lon, alt, battery, etc.)
                if len(parts) > 6:
                    node_data['pubkey'] = parts[6]
                if len(parts) > 7:
                    node_data['role'] = parts[7]
                if len(parts) > 8:
                    lat_str = parts[8].replace('°', '')
                    if lat_str and lat_str != 'N/A':
                        try:
                            node_data['latitude'] = float(lat_str)
                        except:
                            node_data['latitude'] = None
                if len(parts) > 9:
                    lon_str = parts[9].replace('°', '')
                    if lon_str and lon_str != 'N/A':
                        try:
                            node_data['longitude'] = float(lon_str)
                        except:
                            node_data['longitude'] = None
                if len(parts) > 10:
                    alt_str = parts[10].replace('m', '')
                    if alt_str and alt_str != 'N/A':
                        try:
                            node_data['altitude'] = float(alt_str)
                        except:
                            node_data['altitude'] = None
                if len(parts) > 11:
                    battery_str = parts[11]
                    if battery_str and battery_str != 'N/A':
                        if battery_str == 'Powered':
                            node_data['battery_level'] = 'Powered'
                        elif '%' in battery_str:
                            try:
                                node_data['battery_level'] = int(battery_str.replace('%', ''))
                            except:
                                node_data['battery_level'] = battery_str
                        else:
                            node_data['battery_level'] = battery_str
                if len(parts) > 12:
                    ch_util = parts[12].replace('%', '')
                    if ch_util and ch_util != 'N/A':
                        try:
                            node_data['channel_util'] = float(ch_util)
                        except:
                            node_data['channel_util'] = None
                if len(parts) > 13:
                    tx_util = parts[13].replace('%', '')
                    if tx_util and tx_util != 'N/A':
                        try:
                            node_data['tx_util'] = float(tx_util)
                        except:
                            node_data['tx_util'] = None
                if len(parts) > 14:
                    snr_str = parts[14].replace(' dB', '')
                    if snr_str and snr_str != 'N/A':
                        try:
                            node_data['snr'] = float(snr_str)
                        except:
                            node_data['snr'] = None
                if len(parts) > 15:
                    hops_str = parts[15]
                    if hops_str and hops_str != 'N/A':
                        try:
                            node_data['hops_away'] = int(hops_str)
                        except:
                            node_data['hops_away'] = None
                if len(parts) > 17:
                    last_heard = parts[17]
                    if last_heard and last_heard != 'N/A':
                        node_data['last_seen'] = last_heard
                
                # FIXED: Don't update table for each node - let onRefreshFinished do it once
                # This prevents UI freezes and performance issues during refresh
                # self.updateNodesTable()  # REMOVED - causes performance issues
                    
        except Exception as e:
            # Silently ignore parsing errors
            pass
    
    def parseTracerouteOutput(self, output):
        """Parse traceroute command output to extract route information"""
        try:
            if not self.current_traceroute:
                return
                
            # Look for traceroute start indication
            if "Traceroute to" in output or "Route trace" in output:
                self.current_traceroute['timestamp'] = datetime.datetime.now().isoformat()
                self.current_traceroute['route'] = []
                self.current_traceroute['success'] = False
                
            # Look for route hops (format varies, but typically contains node IDs)
            if "!!" in output or output.startswith("!"):
                # Extract node IDs from the output
                node_ids = re.findall(r'![0-9a-fA-F]+', output)
                for node_id in node_ids:
                    if node_id not in self.current_traceroute['route']:
                        self.current_traceroute['route'].append(node_id)
                        
            # Look for success indicators
            if "Route found" in output or "Traceroute complete" in output or self.current_traceroute['target_id'] in output:
                self.current_traceroute['success'] = True
                
            # Look for error indicators
            if "timeout" in output.lower() or "failed" in output.lower() or "error" in output.lower():
                self.current_traceroute['error'] = output.strip()
                
        except Exception as e:
            # Silently ignore parsing errors
            pass
    
    def parseTelemetryOutput(self, output):
        """Parse telemetry command output to extract telemetry data"""
        try:
            if not self.current_telemetry:
                return
                
            # Look for telemetry start indication
            if "Telemetry" in output or "Battery" in output or "Voltage" in output:
                if not self.current_telemetry['timestamp']:
                    self.current_telemetry['timestamp'] = datetime.datetime.now().isoformat()
                
            # Parse battery information
            if "Battery" in output and "%" in output:
                battery_match = re.search(r'(\d+)%', output)
                if battery_match:
                    self.current_telemetry['telemetry_data']['battery'] = int(battery_match.group(1))
                    
            # Parse voltage information
            if "Voltage" in output and "V" in output:
                voltage_match = re.search(r'(\d+\.?\d*)V', output)
                if voltage_match:
                    self.current_telemetry['telemetry_data']['voltage'] = float(voltage_match.group(1))
                    
            # Parse temperature information
            if "Temperature" in output or "°C" in output:
                temp_match = re.search(r'(-?\d+\.?\d*)°?C', output)
                if temp_match:
                    self.current_telemetry['telemetry_data']['temperature'] = float(temp_match.group(1))
                    
            # Parse channel utilization
            if "Channel utilization" in output or "ChUtil" in output:
                util_match = re.search(r'(\d+\.?\d*)%', output)
                if util_match:
                    self.current_telemetry['telemetry_data']['channel_util'] = float(util_match.group(1))
                    
            # Look for success indicators (any telemetry data received)
            if self.current_telemetry['telemetry_data']:
                self.current_telemetry['success'] = True
                
            # Look for error indicators
            if "timeout" in output.lower() or "failed" in output.lower() or "error" in output.lower():
                self.current_telemetry['error'] = output.strip()
                
        except Exception as e:
            # Silently ignore parsing errors
            pass
    
    def onRefreshFinished(self):
        """Handle refresh command completion"""
        # Calculate execution time
        worker_id = id(self.refresh_worker)
        execution_time = None
        if worker_id in self.command_start_times:
            execution_time = time.time() - self.command_start_times[worker_id]
            del self.command_start_times[worker_id]
        
        # Log completion with timing
        if execution_time:
            completion_msg = f"REFRESH COMPLETED in {execution_time:.2f} seconds"
        else:
            completion_msg = "REFRESH COMPLETED"
        
        self.results_display.append("=" * 30 + "\n")
        self.logMessage(completion_msg, 'command')
        
        # Clean up old node data (older than 7 days)
        self.cleanupOldNodeData(7)
        
        # Sync favorites with current discovered nodes
        self.syncFavoritesWithDiscoveredNodes()
        
        # FIXED: Update the nodes table once after all parsing is complete
        # This replaces the individual updates that were removed from parseNodeLine
        self.updateNodesTable()
        
        # Re-enable all buttons
        self.setButtonsEnabled(True)
        
        # Update target combo with new nodes
        self.updateTargetCombo()
        
        # Save discovered nodes
        self.saveDiscoveredNodes()
        
        # Auto-scroll to bottom
        cursor = self.results_display.textCursor()
        cursor.movePosition(cursor.End)
        self.results_display.setTextCursor(cursor)
    
    def onNodeCellChanged(self, row, column):
        """Handle changes to node table cells, especially remarks"""
        if column == 22:  # Remark column (updated index)
            node_id_item = self.nodes_table.item(row, 3)  # ID column (updated index)
            remark_item = self.nodes_table.item(row, 22)  # Remark column
            
            if node_id_item and remark_item:
                node_id = node_id_item.text()
                remark = remark_item.text()
                self.node_remarks[node_id] = remark
                # Auto-save remarks
                self.saveNodeRemarks()
    
    def onNodeCellClicked(self, row, column):
        """Handle cell clicks, especially for favorite column and location data"""
        # Get the node ID for any click on this row
        node_id_item = self.nodes_table.item(row, 3)  # ID column
        if not node_id_item:
            return
            
        node_id = node_id_item.text()
        
        if column == 0:  # Favorite column
            if node_id_item:
                fav_item = self.nodes_table.item(row, 0)
                
                if node_id in self.favorite_nodes:
                    # Remove from favorites
                    self.favorite_nodes.remove(node_id)
                    fav_item.setText("")
                else:
                    # Add to favorites
                    self.favorite_nodes.add(node_id)
                    fav_item.setText("★")
                
                # Auto-save favorites
                self.saveFavorites()
                
                # Update target dropdown immediately
                self.updateTargetCombo()
                
        elif column == 7 or column == 8:  # Latitude or Longitude columns
            self.onLocationClicked(row)
            # Also set as active target
            self.setActiveTarget(node_id)
                
        elif column == 18:  # Traceroutes column - only show summary on single click
            # Single click shows nothing, double click shows detailed view
            # But set as active target
            self.setActiveTarget(node_id)
        
        elif column == 19:  # Telemetry column - only show summary on single click  
            # Single click shows nothing, double click shows detailed view
            # But set as active target
            self.setActiveTarget(node_id)
                
        elif column == 20:  # Public Key column
            if node_id_item:
                self.showPublicKeyHistory(node_id)
                # Also set as active target
                self.setActiveTarget(node_id)
        
        else:
            # For any other column click, set this node as the active target
            self.setActiveTarget(node_id)
    
    def setActiveTarget(self, node_id):
        """Set the specified node as the active target in the dropdown"""
        if not node_id:
            return
            
        # Find the node in the target dropdown and select it
        for i in range(self.target_select.count()):
            item_text = self.target_select.itemText(i)
            
            # Check if this item contains the node_id
            if node_id in item_text:
                self.target_select.setCurrentIndex(i)
                # Visual feedback - briefly highlight the target dropdown
                original_style = self.target_select.styleSheet()
                self.target_select.setStyleSheet("QComboBox { background-color: #90EE90; }")
                
                # Reset style after a short delay
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(1000, lambda: self.target_select.setStyleSheet(original_style))
                return
        
        # If node not found in dropdown, show a message
        self.logMessage(f"Node {node_id} selected in table but not available in target dropdown", 'info')
    
    def showPublicKeyHistory(self, node_id):
        """Show public key history and security information for a specific node"""
        history_text = f"Public Key Security Information for {node_id}\n"
        history_text += "=" * 60 + "\n\n"
        
        # Check if we have key information for this node
        if node_id in self.node_keys:
            key_info = self.node_keys[node_id]
            history_text += f"CURRENT PUBLIC KEY:\n"
            history_text += f"Key: {key_info.get('current_key', 'N/A')}\n"
            history_text += f"First Seen: {key_info.get('first_seen', 'N/A')}\n"
            history_text += f"Last Updated: {key_info.get('last_updated', 'N/A')}\n\n"
            
            # Show key change history if available
            if 'key_history' in key_info and key_info['key_history']:
                history_text += "KEY CHANGE HISTORY:\n"
                history_text += "-" * 30 + "\n"
                for i, change in enumerate(reversed(key_info['key_history'])):
                    history_text += f"{i+1}. {change.get('timestamp', 'N/A')}\n"
                    history_text += f"   Old Key: {change.get('old_key', 'N/A')}\n"
                    history_text += f"   New Key: {change.get('new_key', 'N/A')}\n"
                    history_text += f"   Change Type: {change.get('change_type', 'Unknown')}\n\n"
            else:
                history_text += "No key changes recorded.\n\n"
        else:
            history_text += "No public key information available for this node.\n\n"
        
        # Check for security warnings
        if node_id in self.key_changes_pending:
            history_text += "⚠️ SECURITY WARNING:\n"
            history_text += "This node has pending key changes that require verification.\n\n"
        
        # Show verification status
        if node_id in self.node_keys:
            verified = self.node_keys[node_id].get('verified', False)
            history_text += f"Verification Status: {'✅ Verified' if verified else '❌ Unverified'}\n"
        
        history_text += "\nTip: Key changes may indicate security issues or device replacements."
        
        # Show in a message box
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Public Key Information - {node_id}")
        msg.setText(history_text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
    
    def showDetailedPublicKeyHistory(self, node_id):
        """Show detailed public key history with complete data for a specific node"""
        history_text = f"Detailed Public Key History for {node_id}\n"
        history_text += "=" * 60 + "\n\n"
        
        # Check if we have key information for this node
        if node_id in self.node_keys:
            key_info = self.node_keys[node_id]
            history_text += f"CURRENT PUBLIC KEY DETAILS:\n"
            history_text += f"Key: {key_info.get('current_key', 'N/A')}\n"
            history_text += f"First Seen: {key_info.get('first_seen', 'N/A')}\n"
            history_text += f"Last Updated: {key_info.get('last_updated', 'N/A')}\n"
            history_text += f"Verification Status: {'✅ Verified' if key_info.get('verified', False) else '❌ Unverified'}\n"
            history_text += f"Change Count: {len(key_info.get('key_history', []))}\n\n"
            
            # Show detailed key change history if available
            if 'key_history' in key_info and key_info['key_history']:
                history_text += "COMPLETE KEY CHANGE HISTORY:\n"
                history_text += "-" * 40 + "\n"
                for i, change in enumerate(reversed(key_info['key_history'])):
                    history_text += f"\nChange #{len(key_info['key_history'])-i}:\n"
                    history_text += f"  Timestamp: {change.get('timestamp', 'N/A')}\n"
                    history_text += f"  Old Key: {change.get('old_key', 'N/A')}\n"
                    history_text += f"  New Key: {change.get('new_key', 'N/A')}\n"
                    history_text += f"  Change Type: {change.get('change_type', 'Unknown')}\n"
                    history_text += f"  Acknowledged: {'Yes' if change.get('acknowledged', False) else 'No'}\n"
                    if change.get('note'):
                        history_text += f"  Note: {change['note']}\n"
                    history_text += "  " + "-" * 30 + "\n"
            else:
                history_text += "No key changes recorded.\n\n"
                
            # Security analysis
            history_text += "\nSECURITY ANALYSIS:\n"
            history_text += "-" * 20 + "\n"
            if 'key_history' in key_info and len(key_info['key_history']) > 0:
                history_text += f"⚠️ This node has changed keys {len(key_info['key_history'])} times.\n"
                history_text += "Multiple key changes may indicate:\n"
                history_text += "  • Device replacement\n"
                history_text += "  • Firmware updates\n"
                history_text += "  • Security compromise (rare)\n"
                history_text += "  • Factory reset\n\n"
            else:
                history_text += "✅ No key changes detected - stable identity.\n\n"
                
        else:
            history_text += "No public key information available for this node.\n"
            history_text += "This may indicate:\n"
            history_text += "  • Node discovered through routing (no direct contact)\n"
            history_text += "  • Old data format\n"
            history_text += "  • Node not yet seen with encryption enabled\n\n"
        
        # Check for security warnings
        if node_id in self.key_changes_pending:
            history_text += "\n🚨 SECURITY ALERT:\n"
            history_text += "This node has pending key changes that require your attention!\n"
            history_text += "Please review and acknowledge these changes.\n\n"
        
        history_text += "\nIMPORTANT:\n"
        history_text += "Public key changes are normal for legitimate reasons,\n"
        history_text += "but sudden or frequent changes should be investigated."
        
        # Show in a larger message box
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Detailed Public Key History - {node_id}")
        msg.setText(history_text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setDetailedText("")  # This makes the dialog larger
        msg.exec_()
    
    def onLocationClicked(self, row):
        """Handle clicks on location data to open in map service"""
        lat_item = self.nodes_table.item(row, 7)  # Latitude column
        lng_item = self.nodes_table.item(row, 8)  # Longitude column
        node_id_item = self.nodes_table.item(row, 3)  # ID column
        
        if lat_item and lng_item and node_id_item:
            try:
                latitude = float(lat_item.text())
                longitude = float(lng_item.text())
                node_id = node_id_item.text()
                
                # Generate URL based on selected service
                if self.location_service == "Google Maps":
                    url = f"https://www.google.com/maps?q={latitude},{longitude}"
                elif self.location_service == "Bing Maps":
                    url = f"https://www.bing.com/maps?where={latitude},{longitude}"
                else:  # OpenStreetMap
                    url = f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}&zoom=15"
                
                # Open URL in browser
                import webbrowser
                webbrowser.open(url)
                
            except (ValueError, TypeError):
                QMessageBox.warning(self, "Invalid Location", f"Cannot open location for node {node_id}: invalid coordinates.")
    
    def onNodeCellDoubleClicked(self, row, column):
        """Handle double-clicks for detailed traceroute view"""
        print(f"Double-click detected: row={row}, column={column}")  # Debug output
        if column == 18:  # Traceroutes column
            node_id_item = self.nodes_table.item(row, 3)  # ID column
            if node_id_item:
                node_id = node_id_item.text()
                print(f"Showing detailed traceroute for node: {node_id}")  # Debug output
                self.showDetailedTracerouteHistory(node_id)
            else:
                print("No node ID found in row")  # Debug output
        elif column == 19:  # Telemetry column
            node_id_item = self.nodes_table.item(row, 3)  # ID column
            if node_id_item:
                node_id = node_id_item.text()
                print(f"Showing detailed telemetry for node: {node_id}")  # Debug output
                self.showDetailedTelemetryHistory(node_id)
            else:
                print("No node ID found in row")  # Debug output
        elif column == 20:  # Public Key column
            node_id_item = self.nodes_table.item(row, 3)  # ID column
            if node_id_item:
                node_id = node_id_item.text()
                print(f"Showing detailed key history for node: {node_id}")  # Debug output
                self.showDetailedPublicKeyHistory(node_id)
        else:
            print(f"Double-click on wrong column: {column}, expected 18, 19, or 20")  # Debug output
    
    def onDeleteSelectedNode(self):
        """Delete the currently selected node from the discovered nodes list"""
        current_row = self.nodes_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a node to delete.")
            return
        
        node_id_item = self.nodes_table.item(current_row, 3)  # ID column
        if node_id_item:
            node_id = node_id_item.text()
            
            # Confirm deletion
            reply = QMessageBox.question(
                self, "Confirm Deletion", 
                f"Are you sure you want to delete node {node_id} from the discovered nodes list?\n\n"
                f"This will remove it from the GUI but won't affect the actual Meshtastic network.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Remove from discovered nodes
                if node_id in self.discovered_nodes:
                    del self.discovered_nodes[node_id]
                
                # Remove from favorites if it was favorited
                if node_id in self.favorite_nodes:
                    self.favorite_nodes.remove(node_id)
                
                # Remove from remarks if any
                if node_id in self.node_remarks:
                    del self.node_remarks[node_id]
                
                # Update the table
                self.updateNodesTable()
                
                # Update target combo immediately
                self.updateTargetCombo()
                
                # Save changes
                self.saveDiscoveredNodes()
                self.saveFavorites()
                self.saveNodeRemarks()
                
                QMessageBox.information(self, "Node Deleted", f"Node {node_id} has been removed from the discovered nodes list.")
    
    def onNodeFilterChanged(self):
        """Apply text filter and favorites filter to the node table"""
        filter_text = self.node_filter_input.text().lower()
        favorites_only = self.favorites_only_cb.isChecked()
        
        for row in range(self.nodes_table.rowCount()):
            should_show = True
            
            # Get node ID for favorites check
            node_id_item = self.nodes_table.item(row, 3)  # ID column
            node_id = node_id_item.text() if node_id_item else ""
            
            # Apply favorites filter
            if favorites_only and node_id not in self.favorite_nodes:
                should_show = False
            
            # Apply text filter if there's filter text
            if should_show and filter_text:
                # Search in multiple columns: ID, AKA, User, Hardware, Source, Remark
                search_columns = [3, 4, 2, 5, 21, 22]  # ID, AKA, User, Hardware, Source, Remark
                text_match = False
                
                for col in search_columns:
                    item = self.nodes_table.item(row, col)
                    if item and filter_text in item.text().lower():
                        text_match = True
                        break
                
                if not text_match:
                    should_show = False
            
            # Show/hide row
            self.nodes_table.setRowHidden(row, not should_show)
    
    def onShowColumnDialog(self):
        """Show dialog for column visibility management"""
        dialog = ColumnVisibilityDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # Apply visibility changes
            for col, visible in dialog.visibility_settings.items():
                if visible:
                    self.nodes_table.showColumn(col)
                else:
                    self.nodes_table.hideColumn(col)
    
    def onResetFilters(self):
        """Reset all filters and column visibility to default"""
        # Reset text filter
        self.node_filter_input.clear()
        
        # Reset favorites filter
        self.favorites_only_cb.setChecked(False)
        
        # Show all rows
        for row in range(self.nodes_table.rowCount()):
            self.nodes_table.setRowHidden(row, False)
        
        # Show all columns
        for col in range(self.nodes_table.columnCount()):
            self.nodes_table.showColumn(col)
        
        QMessageBox.information(self, "Filters Reset", "All filters and column visibility have been reset to default.")
    
    def onResetNodesList(self):
        """Reset the nodes list and clean up old/invalid data"""
        reply = QMessageBox.question(
            self, "Reset Nodes List",
            "This will:\n"
            "• Clear all discovered nodes\n"
            "• Clean up favorites to match current nodes\n"
            "• Remove outdated connection data\n"
            "• Reset all node-related files\n\n"
            "Are you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Clear discovered nodes
            self.discovered_nodes = {}
            
            # Clear favorites (they'll be invalid now)
            self.favorite_nodes = set()
            
            # Clear node remarks
            self.node_remarks = {}
            
            # Clear node keys
            self.node_keys = {}
            
            # Clear telemetry stats
            self.telemetry_stats = {}
            
            # Clear history data
            self.traceroute_history = {}
            self.telemetry_history = {}
            
            # Save all cleared data
            self.saveDiscoveredNodes()
            self.saveFavorites()
            self.saveNodeRemarks()
            self.saveNodeKeys()
            self.saveTelemetryStats()
            self.saveTracerouteHistory()
            self.saveTelemetryHistory()
            
            # Update the display
            self.updateNodesTable()
            self.updateTargetCombo()
            
            QMessageBox.information(self, "Reset Complete", 
                "All node data has been reset. You can now refresh the nodes list with current data.")

    def cleanupOldNodeData(self, max_age_days=7):
        """Clean up node data older than specified days"""
        import datetime
        
        current_time = datetime.datetime.now()
        cutoff_time = current_time - datetime.timedelta(days=max_age_days)
        
        nodes_to_remove = []
        
        for node_id, node_data in self.discovered_nodes.items():
            # Check if node has timestamp info
            last_updated_str = node_data.get('last_updated', '')
            if last_updated_str:
                try:
                    last_updated = datetime.datetime.fromisoformat(last_updated_str)
                    if last_updated < cutoff_time:
                        nodes_to_remove.append(node_id)
                except ValueError:
                    # Invalid timestamp format, mark for removal
                    nodes_to_remove.append(node_id)
            else:
                # No timestamp, assume old and mark for removal
                nodes_to_remove.append(node_id)
        
        # Remove old nodes
        for node_id in nodes_to_remove:
            del self.discovered_nodes[node_id]
            
            # Also clean up related data
            if node_id in self.favorite_nodes:
                self.favorite_nodes.remove(node_id)
            if node_id in self.node_remarks:
                del self.node_remarks[node_id]
            if node_id in self.node_keys:
                del self.node_keys[node_id]
        
        if nodes_to_remove:
            print(f"Cleaned up {len(nodes_to_remove)} old node entries")
            self.saveDiscoveredNodes()
            self.saveFavorites()
            self.saveNodeRemarks()
            self.saveNodeKeys()

    def syncFavoritesWithDiscoveredNodes(self):
        """Ensure favorites only contain nodes that exist in discovered nodes"""
        valid_favorites = set()
        
        for node_id in self.favorite_nodes:
            if node_id in self.discovered_nodes:
                valid_favorites.add(node_id)
        
        if len(valid_favorites) != len(self.favorite_nodes):
            removed_count = len(self.favorite_nodes) - len(valid_favorites)
            self.favorite_nodes = valid_favorites
            self.saveFavorites()
            print(f"Removed {removed_count} invalid favorite entries")
    
    def saveTracerouteResult(self):
        """Save the completed traceroute result to history"""
        if not self.current_traceroute or not self.current_traceroute.get('target_id'):
            return
        
        from_node = self.current_traceroute.get('from_node', 'local')
        to_node = self.current_traceroute['target_id']
        
        # Initialize traceroute history structure
        if from_node not in self.traceroute_history:
            self.traceroute_history[from_node] = {}
        if to_node not in self.traceroute_history[from_node]:
            self.traceroute_history[from_node][to_node] = []
        
        # Create traceroute record
        traceroute_record = {
            'timestamp': self.current_traceroute['timestamp'],
            'success': self.current_traceroute['success'],
            'channel': self.current_traceroute['channel'],
            'route': self.current_traceroute['route'].copy(),
            'hops': len(self.current_traceroute['route']),
            'error': self.current_traceroute.get('error', None)
        }
        
        # Add to history (keep last 10 traceroutes per route)
        self.traceroute_history[from_node][to_node].append(traceroute_record)
        if len(self.traceroute_history[from_node][to_node]) > 10:
            self.traceroute_history[from_node][to_node] = self.traceroute_history[from_node][to_node][-10:]
        
        # Save to file and update table
        self.saveTracerouteHistory()
        self.updateNodesTable()
        
        # Clear current traceroute
        self.current_traceroute = None
    
    def saveTelemetryResult(self):
        """Save the completed telemetry result to history"""
        if not self.current_telemetry or not self.current_telemetry.get('target_id'):
            return
        
        from_node = self.current_telemetry.get('from_node', 'local')
        to_node = self.current_telemetry['target_id']
        
        # Initialize telemetry history structure
        if from_node not in self.telemetry_history:
            self.telemetry_history[from_node] = {}
        if to_node not in self.telemetry_history[from_node]:
            self.telemetry_history[from_node][to_node] = []
        
        # Create telemetry record
        telemetry_record = {
            'timestamp': self.current_telemetry['timestamp'],
            'success': self.current_telemetry['success'],
            'telemetry_data': self.current_telemetry['telemetry_data'].copy(),
            'error': self.current_telemetry.get('error', None)
        }
        
        # Add to history (keep last 10 telemetry requests per route)
        self.telemetry_history[from_node][to_node].append(telemetry_record)
        if len(self.telemetry_history[from_node][to_node]) > 10:
            self.telemetry_history[from_node][to_node] = self.telemetry_history[from_node][to_node][-10:]
        
        # Save to file and update table
        self.saveTelemetryHistory()
        self.updateNodesTable()
        
        # Clear current telemetry
        self.current_telemetry = None
    
    def showTracerouteHistory(self, node_id):
        """Show traceroute history summary for a specific node"""
        history_text = f"Traceroute History Summary for {node_id}\n"
        history_text += "=" * 50 + "\n\n"
        
        # Collect all traceroutes involving this node
        found_routes = False
        
        # Routes FROM this node
        if node_id in self.traceroute_history:
            history_text += f"Routes FROM {node_id}:\n"
            for to_node, routes in self.traceroute_history[node_id].items():
                history_text += f"\n  To {to_node} ({len(routes)} attempts):\n"
                for i, route in enumerate(reversed(routes[-3:])):  # Show last 3
                    status = "✓ Success" if route['success'] else "✗ Failed"
                    history_text += f"    {i+1}. {route['timestamp']} - {status}"
                    if route['success'] and route['route']:
                        history_text += f" ({route['hops']} hops)\n"
                    elif route.get('error'):
                        history_text += f" - {route['error']}\n"
                    else:
                        history_text += "\n"
            found_routes = True
        
        # Routes TO this node
        history_text += f"\nRoutes TO {node_id}:\n"
        for from_node, destinations in self.traceroute_history.items():
            if node_id in destinations:
                routes = destinations[node_id]
                history_text += f"\n  From {from_node} ({len(routes)} attempts):\n"
                for i, route in enumerate(reversed(routes[-3:])):  # Show last 3
                    status = "✓ Success" if route['success'] else "✗ Failed"
                    history_text += f"    {i+1}. {route['timestamp']} - {status}"
                    if route['success'] and route['route']:
                        history_text += f" ({route['hops']} hops)\n"
                    elif route.get('error'):
                        history_text += f" - {route['error']}\n"
                    else:
                        history_text += "\n"
                found_routes = True
        
        if not found_routes:
            history_text += "No traceroute history found for this node.\n"
        
        history_text += "\n\nTip: Double-click on the Traceroutes column (number) for detailed route information"
        
        # Show in a message box
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Traceroute Summary - {node_id}")
        msg.setText(history_text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
    
    def showDetailedTracerouteHistory(self, node_id):
        """Show detailed traceroute history with complete routes for a specific node"""
        history_text = f"📍 DETAILED TRACEROUTE HISTORY FOR {node_id}\n"
        history_text += "═" * 65 + "\n\n"
        
        # Collect all traceroutes involving this node
        found_routes = False
        
        # Routes FROM this node
        if node_id in self.traceroute_history:
            history_text += f"🚀 ROUTES FROM {node_id}:\n"
            history_text += "━" * 45 + "\n\n"
            for to_node, routes in self.traceroute_history[node_id].items():
                history_text += f"🎯 Destination: {to_node} ({len(routes)} total attempts)\n\n"
                for i, route in enumerate(reversed(routes)):  # Show all attempts
                    status_icon = "✅" if route['success'] else "❌"
                    history_text += f"   Attempt #{len(routes)-i}: {route['timestamp']}\n"
                    history_text += f"   Status: {status_icon} {'SUCCESS' if route['success'] else 'FAILED'}\n"
                    history_text += f"   Channel: {route['channel']} | Total Hops: {route['hops']}\n\n"
                    
                    if route['success'] and route['route']:
                        history_text += "   🛤️ Complete Route Path:\n"
                        
                        # Group hops by direction
                        towards_hops = [hop for hop in route['route'] if hop.get('direction') == 'towards']
                        back_hops = [hop for hop in route['route'] if hop.get('direction') == 'back']
                        unknown_hops = [hop for hop in route['route'] if hop.get('direction', 'unknown') == 'unknown']
                        
                        if towards_hops:
                            history_text += "      ⬇️ Path to destination:\n"
                            for hop_num, hop in enumerate(towards_hops, 1):
                                history_text += f"         {hop_num:2}. {hop['from']} ➜ {hop['to']} (Signal: {hop['signal']})\n"
                        
                        if back_hops:
                            history_text += "\n      ⬆️ Return path:\n"
                            for hop_num, hop in enumerate(back_hops, 1):
                                history_text += f"         {hop_num:2}. {hop['from']} ➜ {hop['to']} (Signal: {hop['signal']})\n"
                        
                        if unknown_hops:
                            history_text += "\n      ❓ Unknown direction:\n"
                            for hop_num, hop in enumerate(unknown_hops, 1):
                                history_text += f"         {hop_num:2}. {hop['from']} ➜ {hop['to']} (Signal: {hop['signal']})\n"
                    elif route.get('error'):
                        history_text += f"   ⚠️ Error Details: {route['error']}\n"
                    
                    history_text += "\n" + "   " + "·" * 50 + "\n\n"
            found_routes = True
        
        # Routes TO this node
        if found_routes:
            history_text += "\n" + "═" * 65 + "\n\n"
        
        history_text += f"🎯 ROUTES TO {node_id}:\n"
        history_text += "━" * 45 + "\n\n"
        for from_node, destinations in self.traceroute_history.items():
            if node_id in destinations:
                routes = destinations[node_id]
                history_text += f"🚀 From Source: {from_node} ({len(routes)} total attempts)\n\n"
                for i, route in enumerate(reversed(routes)):  # Show all attempts
                    status_icon = "✅" if route['success'] else "❌"
                    history_text += f"   Attempt #{len(routes)-i}: {route['timestamp']}\n"
                    history_text += f"   Status: {status_icon} {'SUCCESS' if route['success'] else 'FAILED'}\n"
                    history_text += f"   Channel: {route['channel']} | Total Hops: {route['hops']}\n\n"
                    
                    if route['success'] and route['route']:
                        history_text += "   🛤️ Complete Route Path:\n"
                        
                        # Group hops by direction
                        towards_hops = [hop for hop in route['route'] if hop.get('direction') == 'towards']
                        back_hops = [hop for hop in route['route'] if hop.get('direction') == 'back']
                        unknown_hops = [hop for hop in route['route'] if hop.get('direction', 'unknown') == 'unknown']
                        
                        if towards_hops:
                            history_text += "      ⬇️ Path to destination:\n"
                            for hop_num, hop in enumerate(towards_hops, 1):
                                history_text += f"         {hop_num:2}. {hop['from']} ➜ {hop['to']} (Signal: {hop['signal']})\n"
                        
                        if back_hops:
                            history_text += "\n      ⬆️ Return path:\n"
                            for hop_num, hop in enumerate(back_hops, 1):
                                history_text += f"         {hop_num:2}. {hop['from']} ➜ {hop['to']} (Signal: {hop['signal']})\n"
                        
                        if unknown_hops:
                            history_text += "\n      ❓ Unknown direction:\n"
                            for hop_num, hop in enumerate(unknown_hops, 1):
                                history_text += f"         {hop_num:2}. {hop['from']} ➜ {hop['to']} (Signal: {hop['signal']})\n"
                    elif route.get('error'):
                        history_text += f"   ⚠️ Error Details: {route['error']}\n"
                    
                    history_text += "\n" + "   " + "·" * 50 + "\n\n"
                found_routes = True
        
        if not found_routes:
            history_text += "📭 No traceroute history found for this node.\n\n"
            history_text += "💡 Tip: Perform traceroutes from/to this node to see routing data here."
        
        # Create custom dialog with better formatting
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"📍 Detailed Traceroute History - {node_id}")
        dialog.resize(750, 600)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Text display with monospace font
        text_display = QTextEdit()
        text_display.setReadOnly(True)
        text_display.setText(history_text)
        
        # Set monospace font for better alignment
        font = QFont("Courier", 9)
        text_display.setFont(font)
        
        # Set background and text colors for better readability
        text_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
                line-height: 1.4;
            }
        """)
        
        layout.addWidget(text_display)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("Close")
        ok_button.setMinimumWidth(80)
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        
        dialog.exec_()
    
    def showTelemetryHistory(self, node_id):
        """Show telemetry history summary for a specific node"""
        history_text = f"Telemetry History Summary for {node_id}\n"
        history_text += "=" * 50 + "\n\n"
        
        # Collect all telemetry involving this node
        found_telem = False
        
        # Telemetry FROM this node
        if node_id in self.telemetry_history:
            history_text += f"Telemetry FROM {node_id}:\n"
            for to_node, telemetry_list in self.telemetry_history[node_id].items():
                history_text += f"\n  To {to_node} ({len(telemetry_list)} requests):\n"
                for i, telem in enumerate(reversed(telemetry_list[-3:])):  # Show last 3
                    status = "✓ Success" if telem['success'] else "✗ Failed"
                    history_text += f"    {i+1}. {telem['timestamp']} - {status}"
                    if telem['success'] and telem['telemetry_data']:
                        data_items = list(telem['telemetry_data'].items())[:3]  # Show first 3 items
                        data_str = ", ".join([f"{k}: {v}" for k, v in data_items])
                        if len(telem['telemetry_data']) > 3:
                            data_str += "..."
                        history_text += f" ({data_str})\n"
                    elif telem.get('error'):
                        history_text += f" - {telem['error']}\n"
                    else:
                        history_text += "\n"
            found_telem = True
        
        # Telemetry TO this node
        history_text += f"\nTelemetry TO {node_id}:\n"
        for from_node, destinations in self.telemetry_history.items():
            if node_id in destinations:
                telemetry_list = destinations[node_id]
                history_text += f"\n  From {from_node} ({len(telemetry_list)} requests):\n"
                for i, telem in enumerate(reversed(telemetry_list[-3:])):  # Show last 3
                    status = "✓ Success" if telem['success'] else "✗ Failed"
                    history_text += f"    {i+1}. {telem['timestamp']} - {status}"
                    if telem['success'] and telem['telemetry_data']:
                        data_items = list(telem['telemetry_data'].items())[:3]  # Show first 3 items
                        data_str = ", ".join([f"{k}: {v}" for k, v in data_items])
                        if len(telem['telemetry_data']) > 3:
                            data_str += "..."
                        history_text += f" ({data_str})\n"
                    elif telem.get('error'):
                        history_text += f" - {telem['error']}\n"
                    else:
                        history_text += "\n"
                found_telem = True
        
        if not found_telem:
            history_text += "No telemetry history found for this node.\n"
        
        history_text += "\n\nTip: Double-click on the Telemetry column (number) for detailed telemetry data"
        
        # Show in a message box
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Telemetry Summary - {node_id}")
        msg.setText(history_text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
    
    def showDetailedTelemetryHistory(self, node_id):
        """Show detailed telemetry history with complete data for a specific node"""
        history_text = f"📊 DETAILED TELEMETRY HISTORY FOR {node_id}\n"
        history_text += "═" * 65 + "\n\n"
        
        # Collect all telemetry involving this node
        found_telem = False
        
        # Telemetry FROM this node
        if node_id in self.telemetry_history:
            history_text += f"📤 TELEMETRY FROM {node_id}:\n"
            history_text += "━" * 45 + "\n\n"
            for to_node, telemetry_list in self.telemetry_history[node_id].items():
                history_text += f"🎯 Destination: {to_node} ({len(telemetry_list)} total requests)\n\n"
                for i, telem in enumerate(reversed(telemetry_list)):  # Show all attempts
                    status_icon = "✅" if telem['success'] else "❌"
                    history_text += f"   Request #{len(telemetry_list)-i}: {telem['timestamp']}\n"
                    history_text += f"   Status: {status_icon} {'SUCCESS' if telem['success'] else 'FAILED'}\n\n"
                    
                    if telem['success'] and 'telemetry_data' in telem:
                        history_text += "   📋 Telemetry Data:\n"
                        for key, value in telem['telemetry_data'].items():
                            history_text += f"      • {key.title():.<20} {value}\n"
                    
                    if not telem['success'] and 'error' in telem:
                        history_text += f"   ⚠️ Error Details: {telem['error']}\n"
                    
                    history_text += "\n" + "   " + "·" * 50 + "\n\n"
            found_telem = True
        
        # Telemetry TO this node
        if found_telem:
            history_text += "\n" + "═" * 65 + "\n\n"
        
        history_text += f"📥 TELEMETRY TO {node_id}:\n"
        history_text += "━" * 45 + "\n\n"
        for from_node, destinations in self.telemetry_history.items():
            if node_id in destinations:
                telemetry_list = destinations[node_id]
                history_text += f"🚀 From Source: {from_node} ({len(telemetry_list)} total requests)\n\n"
                for i, telem in enumerate(reversed(telemetry_list)):  # Show all attempts
                    status_icon = "✅" if telem['success'] else "❌"
                    history_text += f"   Request #{len(telemetry_list)-i}: {telem['timestamp']}\n"
                    history_text += f"   Status: {status_icon} {'SUCCESS' if telem['success'] else 'FAILED'}\n\n"
                    
                    if telem['success'] and 'telemetry_data' in telem:
                        history_text += "   📋 Telemetry Data:\n"
                        for key, value in telem['telemetry_data'].items():
                            history_text += f"      • {key.title():.<20} {value}\n"
                    
                    if not telem['success'] and 'error' in telem:
                        history_text += f"   ⚠️ Error Details: {telem['error']}\n"
                    
                    history_text += "\n" + "   " + "·" * 50 + "\n\n"
                found_telem = True
        
        if not found_telem:
            history_text += "📭 No telemetry history found for this node.\n\n"
            history_text += "💡 Tip: Request telemetry from this node to see data here."
        
        # Create custom dialog with better formatting
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"📊 Detailed Telemetry History - {node_id}")
        dialog.resize(700, 500)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Text display with monospace font for better alignment
        text_display = QTextEdit()
        text_display.setReadOnly(True)
        text_display.setText(history_text)
        
        # Set monospace font for better formatting
        font = QFont("Courier", 9)  # Monospace font
        text_display.setFont(font)
        
        # Set background and text colors for better readability
        text_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
                line-height: 1.4;
            }
        """)
        
        layout.addWidget(text_display)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("Close")
        ok_button.setMinimumWidth(80)
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        
        dialog.exec_()
    
    def saveSettings(self):
        """Save current settings to file"""
        settings = {
            "connection_method": self.connection_method.currentText(),
            "connection_address": self.connection_input.text(),
            "remark": self.remark_input.text(),
            "default_channel": self.channel_input.value(),
            "location_service": getattr(self, 'location_service', 'OpenStreetMap'),
            "node_remarks": self.node_remarks
        }
        
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            QMessageBox.information(self, "Settings Saved", "Settings have been saved successfully.")
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save settings: {str(e)}")
    
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
    
    def loadSettings(self):
        """Load all settings and data from files"""
        # Load node remarks first
        self.loadNodeRemarks()
        
        # Load discovered nodes
        self.loadDiscoveredNodes()
        
        # Load favorites
        self.loadFavorites()
        
        # Load node keys
        self.loadNodeKeys()
        
        # Load telemetry stats
        self.loadTelemetryStats()
        
        # Load connection presets
        self.loadConnectionPresets()
        
        # Load traceroute history
        self.loadTracerouteHistory()
        
        # Load telemetry history
        self.loadTelemetryHistory()
        
        # Load main settings file
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                
                # Restore connection method
                method = settings.get("connection_method", "Serial Port")
                index = self.connection_method.findText(method)
                if index >= 0:
                    self.connection_method.setCurrentIndex(index)
                
                # Restore connection address
                self.connection_input.setText(settings.get("connection_address", ""))
                
                # Restore remark
                self.remark_input.setText(settings.get("remark", ""))
                
                # Restore default channel
                self.channel_input.setValue(settings.get("default_channel", 0))
                
                # Restore location service
                self.location_service = settings.get("location_service", "OpenStreetMap")
                if hasattr(self, 'location_service_combo'):
                    service_index = self.location_service_combo.findText(self.location_service)
                    if service_index >= 0:
                        self.location_service_combo.setCurrentIndex(service_index)
                
                # Restore node remarks (merge with separately loaded ones)
                saved_node_remarks = settings.get("node_remarks", {})
                self.node_remarks.update(saved_node_remarks)
                
            except Exception as e:
                QMessageBox.warning(self, "Warning", f"Failed to load settings: {str(e)}")
        
        # Always update combos after loading all data
        self.updateTargetCombo()
        self.updateNodesTable()
        
        # Clean up any invalid favorites or old data
        self.syncFavoritesWithDiscoveredNodes()
    
    def loadNodeRemarks(self):
        """Load node remarks from file"""
        if os.path.exists(self.node_remarks_file):
            try:
                with open(self.node_remarks_file, 'r') as f:
                    self.node_remarks = json.load(f)
            except Exception:
                self.node_remarks = {}
    
    def saveNodeRemarks(self):
        """Save node remarks to file"""
        try:
            with open(self.node_remarks_file, 'w') as f:
                json.dump(self.node_remarks, f, indent=2)
        except Exception:
            pass
    
    def loadDiscoveredNodes(self):
        """Load discovered nodes from file"""
        if os.path.exists(self.discovered_nodes_file):
            try:
                with open(self.discovered_nodes_file, 'r') as f:
                    self.discovered_nodes = json.load(f)
            except Exception:
                self.discovered_nodes = {}
    
    def saveDiscoveredNodes(self):
        """Save discovered nodes to file"""
        try:
            with open(self.discovered_nodes_file, 'w') as f:
                json.dump(self.discovered_nodes, f, indent=2)
        except Exception:
            pass
    
    def loadFavorites(self):
        """Load favorite nodes from file"""
        if os.path.exists(self.favorites_file):
            try:
                with open(self.favorites_file, 'r') as f:
                    self.favorite_nodes = set(json.load(f))
            except Exception:
                self.favorite_nodes = set()
    
    def saveFavorites(self):
        """Save favorite nodes to file"""
        try:
            with open(self.favorites_file, 'w') as f:
                json.dump(list(self.favorite_nodes), f, indent=2)
        except Exception:
            pass
    
    def loadNodeKeys(self):
        """Load node keys from file"""
        if os.path.exists(self.node_keys_file):
            try:
                with open(self.node_keys_file, 'r') as f:
                    self.node_keys = json.load(f)
            except Exception:
                self.node_keys = {}
    
    def saveNodeKeys(self):
        """Save node keys to file"""
        try:
            with open(self.node_keys_file, 'w') as f:
                json.dump(self.node_keys, f, indent=2)
        except Exception:
            pass
    
    def loadTelemetryStats(self):
        """Load telemetry statistics from file"""
        if os.path.exists(self.telemetry_stats_file):
            try:
                with open(self.telemetry_stats_file, 'r') as f:
                    self.telemetry_stats = json.load(f)
            except Exception:
                self.telemetry_stats = {}
    
    def saveTelemetryStats(self):
        """Save telemetry statistics to file"""
        try:
            with open(self.telemetry_stats_file, 'w') as f:
                json.dump(self.telemetry_stats, f, indent=2)
        except Exception:
            pass
    
    def loadConnectionPresets(self):
        """Load connection presets from file"""
        if os.path.exists(self.connection_presets_file):
            try:
                with open(self.connection_presets_file, 'r') as f:
                    self.connection_presets = json.load(f)
            except Exception:
                self.connection_presets = {}
        # Update the preset combo box after loading
        self.updatePresetCombo()
    
    def saveConnectionPresets(self):
        """Save connection presets to file"""
        try:
            with open(self.connection_presets_file, 'w') as f:
                json.dump(self.connection_presets, f, indent=2)
        except Exception:
            pass
    
    def loadTracerouteHistory(self):
        """Load traceroute history from file"""
        if os.path.exists(self.traceroute_history_file):
            try:
                with open(self.traceroute_history_file, 'r') as f:
                    self.traceroute_history = json.load(f)
            except Exception:
                self.traceroute_history = {}
    
    def saveTracerouteHistory(self):
        """Save traceroute history to file"""
        try:
            with open(self.traceroute_history_file, 'w') as f:
                json.dump(self.traceroute_history, f, indent=2)
        except Exception:
            pass
    
    def loadTelemetryHistory(self):
        """Load telemetry history from file"""
        if os.path.exists(self.telemetry_history_file):
            try:
                with open(self.telemetry_history_file, 'r') as f:
                    self.telemetry_history = json.load(f)
            except Exception:
                self.telemetry_history = {}
    
    def saveTelemetryHistory(self):
        """Save telemetry history to file"""
        try:
            with open(self.telemetry_history_file, 'w') as f:
                json.dump(self.telemetry_history, f, indent=2)
        except Exception:
            pass
    
    def onExportCSV(self):
        """Export node data to CSV file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export to CSV", "meshtastic_nodes.csv", "CSV Files (*.csv)")
        
        if file_path:
            try:
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    import csv
                    writer = csv.writer(f)
                    
                    # Write header
                    headers = [
                        "Favorite", "SNR", "User", "ID", "AKA", "Hardware", "Battery", 
                        "Latitude", "Longitude", "Altitude", "Last Heard", "Hops", 
                        "Via MQTT", "Ch. Util", "TX Airtime", "Neighbors", "Uptime", 
                        "Voltage", "Traceroutes", "Telemetry", "Public Key", "Remark"
                    ]
                    writer.writerow(headers)
                    
                    # Write data rows
                    for row in range(self.nodes_table.rowCount()):
                        if not self.nodes_table.isRowHidden(row):
                            row_data = []
                            for col in range(self.nodes_table.columnCount()):
                                item = self.nodes_table.item(row, col)
                                row_data.append(item.text() if item else "")
                            writer.writerow(row_data)
                
                QMessageBox.information(self, "Export Complete", f"Data exported to {file_path}")
                
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Failed to export data: {str(e)}")
    
    def updateNodesTable(self):
        """Update the nodes table with current data"""
        # Clear existing data
        self.nodes_table.setRowCount(0)
        
        # Add discovered nodes to table
        for node_id, node_data in self.discovered_nodes.items():
            row = self.nodes_table.rowCount()
            self.nodes_table.insertRow(row)
            
            # Column 0: Favorite (★)
            fav_item = QTableWidgetItem("★" if node_id in self.favorite_nodes else "")
            self.nodes_table.setItem(row, 0, fav_item)
            
            # Column 1: N (Node number - just use row number + 1)
            n_item = QTableWidgetItem(str(row + 1))
            self.nodes_table.setItem(row, 1, n_item)
            
            # Column 2: User
            user_item = QTableWidgetItem(node_data.get('user', ''))
            self.nodes_table.setItem(row, 2, user_item)
            
            # Column 3: ID
            id_item = QTableWidgetItem(node_id)
            self.nodes_table.setItem(row, 3, id_item)
            
            # Column 4: AKA
            aka_item = QTableWidgetItem(node_data.get('aka', ''))
            self.nodes_table.setItem(row, 4, aka_item)
            
            # Column 5: Hardware
            hw_item = QTableWidgetItem(node_data.get('hardware', ''))
            self.nodes_table.setItem(row, 5, hw_item)
            
            # Column 6: Role
            role_item = QTableWidgetItem(node_data.get('role', ''))
            self.nodes_table.setItem(row, 6, role_item)
            
            # Column 7: Latitude
            lat_item = QTableWidgetItem(str(node_data.get('latitude', '')))
            self.nodes_table.setItem(row, 7, lat_item)
            
            # Column 8: Longitude  
            lng_item = QTableWidgetItem(str(node_data.get('longitude', '')))
            self.nodes_table.setItem(row, 8, lng_item)
            
            # Column 9: Altitude
            alt_item = QTableWidgetItem(str(node_data.get('altitude', '')))
            self.nodes_table.setItem(row, 9, alt_item)
            
            # Column 10: Battery
            battery_val = node_data.get('battery_level', '')
            battery_str = str(battery_val) if battery_val != '' else ''
            if battery_str and battery_str != 'None' and battery_str.isdigit():
                battery_str += '%'
            battery_item = QTableWidgetItem(battery_str)
            self.nodes_table.setItem(row, 10, battery_item)
            
            # Column 11: Ch.Util (Channel Utilization)
            ch_util_val = node_data.get('channel_util', '')
            ch_util_str = str(ch_util_val) if ch_util_val != '' else ''
            if ch_util_str and ch_util_str != 'None':
                try:
                    ch_util_str = f"{float(ch_util_str):.2f}%"
                except:
                    pass
            ch_util_item = QTableWidgetItem(ch_util_str)
            self.nodes_table.setItem(row, 11, ch_util_item)
            
            # Column 12: Tx.Util (Transmit Utilization)
            tx_util_val = node_data.get('tx_util', '')
            tx_util_str = str(tx_util_val) if tx_util_val != '' else ''
            if tx_util_str and tx_util_str != 'None':
                try:
                    tx_util_str = f"{float(tx_util_str):.2f}%"
                except:
                    pass
            tx_util_item = QTableWidgetItem(tx_util_str)
            self.nodes_table.setItem(row, 12, tx_util_item)
            
            # Column 13: SNR
            snr_val = node_data.get('snr', '')
            snr_str = str(snr_val) if snr_val != '' else ''
            if snr_str and snr_str != 'None':
                try:
                    snr_str = f"{float(snr_str):.1f} dB"
                except:
                    pass
            snr_item = QTableWidgetItem(snr_str)
            self.nodes_table.setItem(row, 13, snr_item)
            
            # Column 14: Hops
            hops_val = node_data.get('hops_away', '')
            hops_str = str(hops_val) if hops_val != '' and hops_val is not None else ''
            hops_item = QTableWidgetItem(hops_str)
            self.nodes_table.setItem(row, 14, hops_item)
            
            # Column 15: Channel
            channel_item = QTableWidgetItem(str(node_data.get('channel', '')))
            self.nodes_table.setItem(row, 15, channel_item)
            
            # Column 16: LastHeard (from the node itself)
            heard_item = QTableWidgetItem(node_data.get('last_seen', ''))  # Node's own last_seen time
            self.nodes_table.setItem(row, 16, heard_item)
            
            # Column 17: Last Seen by Client (when GUI last updated this node)
            last_updated = node_data.get('last_updated', '')
            if last_updated:
                try:
                    # Convert from ISO format to readable format
                    dt = datetime.datetime.fromisoformat(last_updated)
                    client_seen = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    client_seen = last_updated
            else:
                client_seen = ''
            client_seen_item = QTableWidgetItem(client_seen)
            self.nodes_table.setItem(row, 17, client_seen_item)
            
            # Column 18: Traceroutes (count)
            tr_count = 0
            for from_node in self.traceroute_history:
                if node_id in self.traceroute_history[from_node]:
                    tr_count += len(self.traceroute_history[from_node][node_id])
            if node_id in self.traceroute_history:
                for to_node in self.traceroute_history[node_id]:
                    tr_count += len(self.traceroute_history[node_id][to_node])
            tr_item = QTableWidgetItem(str(tr_count) if tr_count > 0 else '')
            self.nodes_table.setItem(row, 18, tr_item)
            
            # Column 19: Telemetry (count)
            telem_count = 0
            for from_node in self.telemetry_history:
                if node_id in self.telemetry_history[from_node]:
                    telem_count += len(self.telemetry_history[from_node][node_id])
            if node_id in self.telemetry_history:
                for to_node in self.telemetry_history[node_id]:
                    telem_count += len(self.telemetry_history[node_id][to_node])
            telem_item = QTableWidgetItem(str(telem_count) if telem_count > 0 else '')
            self.nodes_table.setItem(row, 19, telem_item)
            
            # Column 20: Public Key (truncated)
            pub_key = node_data.get('pubkey', '')
            if pub_key and len(pub_key) > 8:
                pub_key_display = pub_key[:8] + "..."
            else:
                pub_key_display = pub_key
            pub_key_item = QTableWidgetItem(pub_key_display)
            if node_id in self.key_changes_pending:
                from PyQt5.QtGui import QColor
                pub_key_item.setBackground(QColor(255, 255, 0))  # Yellow background
            self.nodes_table.setItem(row, 20, pub_key_item)
            
            # Column 21: Source (connection preset)
            source_preset = node_data.get('source_preset', 'Unknown')
            source_method = node_data.get('source_method', '')
            if source_preset == "Default" or not source_preset:
                source_display = source_method or 'Unknown'
            else:
                source_display = f"{source_preset} ({source_method})"
            source_item = QTableWidgetItem(source_display)
            self.nodes_table.setItem(row, 21, source_item)
            
            # Column 22: Remark
            remark = self.node_remarks.get(node_id, '')
            remark_item = QTableWidgetItem(remark)
            self.nodes_table.setItem(row, 22, remark_item)
            
            # Highlight nodes with key changes (entire row)
            if node_id in self.key_changes_pending:
                from PyQt5.QtGui import QColor
                for col in range(self.nodes_table.columnCount()):
                    item = self.nodes_table.item(row, col)
                    if item:
                        item.setBackground(QColor(255, 200, 200))  # Light red background
    
    def updateTargetCombo(self):
        """Update the target selection combo box"""
        current_selection = self.target_select.currentText()
        self.target_select.clear()
        
        # Add discovered nodes (favorites first)
        favorites = []
        others = []
        
        for node_id, node_data in self.discovered_nodes.items():
            display_text = f"{node_id} ({node_data.get('aka', 'N/A')})"
            if node_id in self.favorite_nodes:
                favorites.append(display_text)
            else:
                others.append(display_text)
        
        # Sort and add favorites first
        for item in sorted(favorites):
            self.target_select.addItem(f"★ {item}")
        
        # Then add others
        for item in sorted(others):
            self.target_select.addItem(item)
        
        # Restore selection if it still exists
        if current_selection:
            index = self.target_select.findText(current_selection)
            if index >= 0:
                self.target_select.setCurrentIndex(index)
    
    def cleanupDataFiles(self):
        """Clean up any duplicate or old format data files"""
        cleanup_files = [
            "favorite_nodes.json",  # Old format
            "favorites_backup.json",  # Backup files
            "discovered_nodes_old.json",  # Old format
            "node_list.json",  # Alternative names
            "nodes.json"  # Alternative names
        ]
        
        removed_files = []
        for filename in cleanup_files:
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                    removed_files.append(filename)
                except Exception as e:
                    print(f"Could not remove {filename}: {e}")
        
        if removed_files:
            print(f"Cleaned up old data files: {', '.join(removed_files)}")
            return len(removed_files)
        return 0


# Column visibility dialog
class ColumnVisibilityDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Column Visibility")
        self.setModal(True)
        
        # Get column headers
        table = parent.nodes_table
        column_names = [
            "★", "SNR", "User", "ID", "AKA", "Hardware", "Battery", "Latitude", 
            "Longitude", "Altitude", "Last Heard", "Hops", "Via MQTT", "Ch. Util", 
            "TX Airtime", "Neighbors", "Uptime", "Voltage", "Traceroutes", "Telemetry", 
            "Public Key", "Remark"
        ]
        
        # Store current visibility
        self.visibility_settings = {}
        
        layout = QVBoxLayout()
        
        # Create checkboxes for each column
        for i, name in enumerate(column_names):
            checkbox = QCheckBox(name)
            checkbox.setChecked(not table.isColumnHidden(i))
            self.visibility_settings[i] = checkbox
            layout.addWidget(checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        

        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def accept(self):
        # Update visibility settings
        for col, checkbox in self.visibility_settings.items():
            self.visibility_settings[col] = checkbox.isChecked()
        super().accept()


# Main execution
if __name__ == "__main__":
    print("Starting Meshtastic GUI...")
    
    try:
        import sys
        from PyQt5.QtWidgets import QApplication
        
        app = QApplication(sys.argv)
        print("QApplication created successfully")
        
        # Create and show the main window
        window = MeshtasticClientGUI()
        print("Main window created")
        
        window.show()
        print("Window shown - should be visible now")
        
        # Make sure window is on top
        window.raise_()
        window.activateWindow()
        
        print("Starting Qt event loop...")
        sys.exit(app.exec_())
        
    except Exception as e:
        print(f"ERROR: Failed to start application: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)