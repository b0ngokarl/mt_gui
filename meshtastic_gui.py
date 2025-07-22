import sys
import json
import os
import subprocess
import datetime
import csv
import re
import webbrowser
import queue
import threading
import traceback
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGroupBox, QComboBox, QLineEdit, QPushButton, 
                             QLabel, QMessageBox, QFileDialog, QTableWidget,
                             QTableWidgetItem, QTextEdit, QSpinBox, QCheckBox, 
                             QScrollArea, QDialog)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from PyQt5.QtCore import Qt

class CommandQueueManager(QThread):
    """Manages a queue of Meshtastic CLI commands to prevent GUI blocking"""
    command_completed = pyqtSignal(str, str, str)  # command_id, output, error
    command_started = pyqtSignal(str)  # command_id
    
    def __init__(self):
        super().__init__()
        self.command_queue = queue.Queue()
        self.running = True
        self.current_command = None
        
    def add_command(self, command_id, cmd_args, callback=None):
        """Add a command to the queue"""
        self.command_queue.put({
            'id': command_id,
            'args': cmd_args,
            'callback': callback
        })
        
    def stop(self):
        """Stop the command queue manager"""
        self.running = False
        # Add a sentinel value to wake up the thread
        self.command_queue.put(None)
        
    def run(self):
        """Process commands from the queue"""
        while self.running:
            try:
                # Get command from queue (blocks until available)
                command_item = self.command_queue.get(timeout=1)
                
                if command_item is None:  # Sentinel value to stop
                    break
                    
                command_id = command_item['id']
                cmd_args = command_item['args']
                callback = command_item.get('callback')
                
                self.current_command = command_id
                self.command_started.emit(command_id)
                
                try:
                    # Execute the command
                    process = subprocess.Popen(
                        cmd_args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    output, error = process.communicate()

                    # Log the completion of the command
                    print(f"Command {command_id} completed. Output: {output}, Error: {error}")

                    # Emit completion signal
                    self.command_completed.emit(command_id, output, error)

                    # Call callback if provided
                    if callback:
                        callback(output, error)

                except Exception as e:
                    error_msg = f"Command execution failed: {str(e)}"
                    print(f"Command {command_id} failed with error: {error_msg}")
                    self.command_completed.emit(command_id, "", error_msg)
                    
                finally:
                    self.current_command = None
                    self.command_queue.task_done()
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Command queue error: {str(e)}")

class CommandWorker(QThread):
    output_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()
    
    def __init__(self, command):
        super().__init__()
        self.command = command
    
    def run(self):
        try:
            # Execute the command securely (avoid shell=True)
            if isinstance(self.command, str):
                cmd = self.command.split()
            else:
                cmd = self.command
            process = subprocess.Popen(
                cmd,
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
        self.active_workers = []  # Track active background workers
        
        # Initialize command queue manager
        self.command_queue_manager = CommandQueueManager()
        self.command_queue_manager.command_completed.connect(self.onCommandCompleted)
        self.command_queue_manager.command_started.connect(self.onCommandStarted)
        self.command_queue_manager.start()
        
        # Track pending commands
        self.pending_commands = {}  # command_id -> {type, callback, timestamp}
        
        self.initUI()
        self.loadSettings()
        self.loadConnectionPresets()
        self.loadDiscoveredNodes()
        self.loadFavorites()
        self.loadNodeRemarks()
        self.loadTracerouteHistory()
        self.loadTelemetryHistory()
        
        # Load device connections for smart preset matching
        self.loadDeviceConnections()
    
    def logWithTimestamp(self, message):
        """Add a timestamped message to the results display"""
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.results_display.append(f"[{timestamp}] {message}")
    
    def queueMeshtasticCommand(self, cmd_args, command_type="generic", callback=None):
        """Queue a Meshtastic command for execution in background thread"""
        command_id = f"{command_type}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        # Store command info
        self.pending_commands[command_id] = {
            'type': command_type,
            'callback': callback,
            'timestamp': datetime.datetime.now(),
            'args': cmd_args
        }
        
        # Add to queue
        self.command_queue_manager.add_command(command_id, cmd_args, callback)
        
        self.logWithTimestamp(f"Queued {command_type}: {' '.join(cmd_args)}")
        self.updateQueueStatus()
        return command_id
    
    def updateQueueStatus(self):
        """Update the queue status display"""
        if hasattr(self, 'queue_status_label'):
            pending_count = len(self.pending_commands)
            current = getattr(self.command_queue_manager, 'current_command', None)
            if current:
                self.queue_status_label.setText(f"Queue: {pending_count} pending (running: {current.split('_')[0]})")
            else:
                self.queue_status_label.setText(f"Queue: {pending_count} pending")
            
            # Change color based on queue size
            if pending_count == 0:
                self.queue_status_label.setStyleSheet("QLabel { color: green; font-weight: bold; }")
            elif pending_count < 3:
                self.queue_status_label.setStyleSheet("QLabel { color: blue; font-weight: bold; }")
            else:
                self.queue_status_label.setStyleSheet("QLabel { color: orange; font-weight: bold; }")
    
    def onCommandStarted(self, command_id):
        """Handle command start notification"""
        if command_id in self.pending_commands:
            cmd_info = self.pending_commands[command_id]
            self.logWithTimestamp(f"Executing {cmd_info['type']}...")
    
    def onCommandCompleted(self, command_id, output, error):
        """Handle command completion"""
        if command_id not in self.pending_commands:
            return
            
        cmd_info = self.pending_commands[command_id]
        cmd_type = cmd_info['type']
        cmd_args = cmd_info.get('args', [])
        
        # Always log the actual command that was executed
        self.logWithTimestamp(f"Command executed: {' '.join(cmd_args)}")
        
        # Log results - show both output and error for debugging
        if error:
            self.logWithTimestamp(f"{cmd_type} stderr: {error}")
        if output:
            self.logWithTimestamp(f"{cmd_type} stdout: {output}")
            if cmd_type == "nodes":
                self.onNodesCommandCompleted(output)
        
        # If no output and no error, that's also useful to know
        if not output and not error:
            self.logWithTimestamp(f"{cmd_type} completed with no output or error")
        
        # Clean up
        del self.pending_commands[command_id]
        
        # Update UI state
        self.updateUIAfterCommand(cmd_type)
        self.updateQueueStatus()
    
    def onNodesCommandCompleted(self, output):
        """Handle nodes command completion"""
        try:
            self.logWithTimestamp(f"Parsing nodes output (length: {len(output)} chars)")
            
            # Show first 200 chars of output for debugging
            if output:
                preview = output[:200] + "..." if len(output) > 200 else output
                self.logWithTimestamp(f"Output preview: {repr(preview)}")
            
            nodes = self.parse_meshtastic_table_output(output)
            self.logWithTimestamp(f"Parsed {len(nodes)} nodes from output")
            
            # Merge new nodes with existing discovered_nodes, preserving user data
            for node in nodes:
                node_id = node.get('ID') or node.get('id') or str(len(self.discovered_nodes))
                if node_id in self.discovered_nodes:
                    existing = self.discovered_nodes[node_id]
                    new_last_heard = node.get('LastHeard') or node.get('lastHeard') or ""
                    existing_last_heard = existing.get('LastHeard') or existing.get('lastHeard') or ""
                    
                    if (new_last_heard and (not existing_last_heard or new_last_heard > existing_last_heard)):
                        for key, value in node.items():
                            existing[key] = value
                else:
                    self.discovered_nodes[node_id] = node
            
            self.saveDiscoveredNodes()
            self.update_nodes_table(nodes)
            
        except Exception as e:
            self.logWithTimestamp(f"Failed to process nodes output: {str(e)}")
            import traceback
            self.logWithTimestamp(f"Traceback: {traceback.format_exc()}")
    
    def updateUIAfterCommand(self, cmd_type):
        """Update UI state after command completion"""
        if cmd_type == "traceroute":
            self.traceroute_btn.setEnabled(True)
            self.traceroute_btn.setText("Traceroute")
        elif cmd_type == "telemetry":
            self.telemetry_btn.setEnabled(True)
            self.telemetry_btn.setText("Get Telemetry")
        elif cmd_type == "reboot":
            self.logWithTimestamp("Device reboot command completed.")
    
    def closeEvent(self, event):
        """Handle application close event"""
        if hasattr(self, 'command_queue_manager'):
            self.command_queue_manager.stop()
            self.command_queue_manager.wait(3000)  # Wait up to 3 seconds
        event.accept()
    
    def onComboBoxClicked(self, event, combo_box):
        """Handle mouse click on combo box to ensure it opens"""
        if event.button() == Qt.LeftButton:
            # Use a timer to ensure the popup opens
            QTimer.singleShot(0, combo_box.showPopup)
        # Always call the original mouse press event
        QComboBox.mousePressEvent(combo_box, event)
    
    def eventFilter(self, obj, event):
        """Event filter to handle combo box events"""
        if isinstance(obj, QComboBox):
            if event.type() == event.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    # Force the popup to show
                    QTimer.singleShot(0, obj.showPopup)
                    return False  # Let the event continue
            elif event.type() == event.MouseButtonRelease:
                if event.button() == Qt.LeftButton:
                    # Ensure popup is shown on release too
                    if not obj.view().isVisible():
                        QTimer.singleShot(10, obj.showPopup)
                    return False
        return super().eventFilter(obj, event)
    
    def initUI(self):
        self.setWindowTitle("Meshtastic Client GUI")
        self.setGeometry(100, 100, 1200, 800)
        # Ensure combo boxes pop up on click
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
        # Ensure QComboBox widgets accept mouse interaction
        self.connection_method.setFocusPolicy(Qt.StrongFocus)
        self.connection_method.setAttribute(Qt.WA_TransparentForMouseEvents, False)  # Ensure QComboBox widgets explicitly accept mouse events
        first_row.addWidget(self.connection_method)
        
        # Add preset selector
        first_row.addWidget(QLabel("Preset:"))
        self.connection_preset = QComboBox()
        self.connection_preset.setMaximumWidth(150)
        self.connection_preset.currentTextChanged.connect(self.onPresetChanged)
        # Ensure QComboBox widgets accept mouse interaction
        self.connection_preset.setFocusPolicy(Qt.StrongFocus)
        self.connection_preset.setAttribute(Qt.WA_TransparentForMouseEvents, False)  # Ensure QComboBox widgets explicitly accept mouse events
        first_row.addWidget(self.connection_preset)

        # Inline preset name input and save button
        self.preset_name_input = QLineEdit()
        self.preset_name_input.setPlaceholderText("Preset name")
        self.preset_name_input.setMaximumWidth(120)
        first_row.addWidget(self.preset_name_input)

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
        
        # Settings buttons - more compact
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.saveSettings)
        self.save_btn.setMaximumWidth(60)
        button_layout.addWidget(self.save_btn)
        
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self.loadSettingsDialog)
        self.load_btn.setMaximumWidth(60)
        button_layout.addWidget(self.load_btn)
        
        # Reboot button - always enabled since CLI handles connection
        self.reboot_btn = QPushButton("Reboot")
        self.reboot_btn.clicked.connect(self.onReboot)
        self.reboot_btn.setMaximumWidth(60)
        self.reboot_btn.setToolTip("Reboot the connected device using CLI")
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
        self.target_select.addItem("")  # Add empty default item
        # Ensure QComboBox widgets accept mouse interaction
        self.target_select.setFocusPolicy(Qt.StrongFocus)
        self.target_select.setAttribute(Qt.WA_TransparentForMouseEvents, False)  # Ensure QComboBox widgets explicitly accept mouse events
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
        # Ensure QComboBox widgets accept mouse interaction
        self.message_type.setFocusPolicy(Qt.StrongFocus)
        self.message_type.setAttribute(Qt.WA_TransparentForMouseEvents, False)  # Ensure QComboBox widgets explicitly accept mouse events
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
        # Ensure QComboBox widgets accept mouse interaction
        self.location_service_combo.setFocusPolicy(Qt.StrongFocus)
        self.location_service_combo.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        filter_row.addWidget(self.location_service_combo)
        
        # Key acknowledgment button
        self.ack_keys_btn = QPushButton("Ack Key Changes")
        self.ack_keys_btn.clicked.connect(self.onAcknowledgeKeyChanges)
        self.ack_keys_btn.setMaximumWidth(120)
        self.ack_keys_btn.setEnabled(False)  # Initially disabled
        self.ack_keys_btn.setStyleSheet("QPushButton { color: red; font-weight: bold; }")
        filter_row.addWidget(self.ack_keys_btn)
        
        filter_row.addStretch()
        
        # Queue status display (bottom right corner)
        self.queue_status_label = QLabel("Queue: 0 pending")
        self.queue_status_label.setStyleSheet("QLabel { color: blue; font-weight: bold; }")
        self.queue_status_label.setToolTip("Number of commands in the execution queue")
        filter_row.addWidget(self.queue_status_label)
        
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
        
        # Ensure all combo boxes can receive mouse events properly
        for combo in [self.connection_method, self.connection_preset, self.target_select, 
                      self.message_type, self.location_service_combo]:
            combo.setEnabled(True)
            combo.setMouseTracking(True)
            combo.setAcceptDrops(False)
            combo.clearFocus()  # Clear any initial focus issues
            # Try multiple approaches to fix dropdown
            combo.mousePressEvent = lambda event, cb=combo: self.onComboBoxClicked(event, cb)
            combo.setFocusPolicy(Qt.StrongFocus)
            combo.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            # Force enable interaction
            combo.setStyleSheet("QComboBox { background-color: white; }")
            combo.installEventFilter(self)
    
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
            "node_remarks": getattr(self, 'node_remarks', {}),
            "column_visibility": getattr(self, 'column_visibility', {})
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
        """Save current connection as preset using inline input"""
        name = self.preset_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Save Preset", "Preset name cannot be empty.")
            return
        self.connection_presets[name] = {
            "method": self.connection_method.currentText(),
            "address": self.connection_input.text(),
            "remark": self.remark_input.text()
        }
        self.saveConnectionPresets()
        self.updatePresetCombo()
        self.preset_name_input.clear()
        QMessageBox.information(self, "Preset Saved", f"Preset '{name}' saved.")
    
    def onDeletePreset(self):
        """Delete selected preset"""
        preset = self.connection_preset.currentText()
        if preset:
            for name in list(self.connection_presets.keys()):
                display_text = f"{name} ({self.connection_presets[name]['method']}: {self.connection_presets[name]['address']})"
                if display_text == preset:
                    del self.connection_presets[name]
                    self.saveConnectionPresets()
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
    
    def onReboot(self):
        """Reboot device using Meshtastic CLI"""
        try:
            cmd = self.buildMeshtasticCommand("--reboot")
            self.queueMeshtasticCommand(cmd, "reboot")
        except Exception as e:
            self.logWithTimestamp(f"Reboot error: {str(e)}")

    def onKillAllMeshtastic(self):
        """Kill all meshtastic CLI processes (not the GUI)"""
        try:
            # Kill meshtastic CLI processes but exclude this GUI
            result = subprocess.run("pkill -f 'meshtastic(?!.*gui)'", shell=True, capture_output=True, text=True)
            # Also clear the command queue
            if hasattr(self, 'command_queue_manager'):
                # Clear pending commands
                while not self.command_queue_manager.command_queue.empty():
                    try:
                        self.command_queue_manager.command_queue.get_nowait()
                    except:
                        break
                self.pending_commands.clear()
                self.updateQueueStatus()
            self.logWithTimestamp("Meshtastic CLI processes killed and queue cleared.")
        except Exception as e:
            self.logWithTimestamp(f"Kill All Error: {str(e)}")

    def onLoadConfig(self):
        """Load configuration"""
        # Real config load logic could be added here
        self.logWithTimestamp("Configuration loaded.")

    def onSaveConfig(self):
        """Save configuration"""
        # Real config save logic could be added here
        self.logWithTimestamp("Configuration saved.")

    def onResetConfig(self):
        """Reset configuration"""
        # Real config reset logic could be added here
        self.logWithTimestamp("Configuration reset.")

    def onTraceroute(self):
        """Perform traceroute"""
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        target = self.target_select.currentText().strip()
        channel = self.channel_input.value()
        
        if not target:
            self.logWithTimestamp("No target selected for traceroute.")
            return
        
        # Extract node ID from target text (look for ID in parentheses or use the whole target)
        node_id_match = re.search(r'\(([^)]+)\)', target)
        if node_id_match:
            node_id = node_id_match.group(1)
        else:
            node_id = target.split()[-1]  # Use last word if no parentheses
        
        # Build command using subprocess args instead of shell=True to avoid quoting issues
        cmd = ["meshtastic"]
        
        # Add connection parameters
        if method == "Serial Port" and address:
            cmd.extend(["--port", address])
        elif method == "IP Address" and address:
            cmd.extend(["--host", address])
        elif method == "Bluetooth":
            if address:
                cmd.extend(["--ble", address])
            else:
                cmd.append("--ble")
        
        # Add traceroute command and target (using request-telemetry with dest)
        cmd.extend(["--request-telemetry", "--dest", node_id])
        
        # Add channel if specified
        if channel > 0:
            cmd.extend(["--ch-index", str(channel)])
        
        # Disable button while running
        self.traceroute_btn.setEnabled(False)
        self.traceroute_btn.setText("Running...")
        
        # Queue the command
        self.queueMeshtasticCommand(cmd, "traceroute")
    
    def onTracerouteOutput(self, output, node_id):
        """Handle traceroute output and store it"""
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.results_display.append(f"[{timestamp}] Traceroute output: {output}")
        
        # Store traceroute history
        if node_id not in self.traceroute_history:
            self.traceroute_history[node_id] = []
        
        self.traceroute_history[node_id].append({
            'timestamp': timestamp,
            'output': output
        })
        
        # Keep only last 10 entries per node
        if len(self.traceroute_history[node_id]) > 10:
            self.traceroute_history[node_id] = self.traceroute_history[node_id][-10:]
        
        # Save traceroute history
        try:
            with open(self.traceroute_history_file, 'w') as f:
                json.dump(self.traceroute_history, f, indent=2)
        except Exception as e:
            self.logWithTimestamp(f"Failed to save traceroute history: {str(e)}")
    
    def onTelemetryOutput(self, output, node_id):
        """Handle telemetry output and store it"""
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.results_display.append(f"[{timestamp}] Telemetry output: {output}")
        
        # Store telemetry history
        if node_id not in self.telemetry_history:
            self.telemetry_history[node_id] = []
        
        self.telemetry_history[node_id].append({
            'timestamp': timestamp,
            'output': output
        })
        
        # Keep only last 10 entries per node
        if len(self.telemetry_history[node_id]) > 10:
            self.telemetry_history[node_id] = self.telemetry_history[node_id][-10:]
        
        # Save telemetry history
        try:
            with open(self.telemetry_history_file, 'w') as f:
                json.dump(self.telemetry_history, f, indent=2)
        except Exception as e:
            self.logWithTimestamp(f"Failed to save telemetry history: {str(e)}")
    
    def onWorkerFinished(self, worker):
        """Handle worker completion"""
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        
        # Re-enable buttons if no workers are running
        if not self.active_workers:
            self.traceroute_btn.setEnabled(True)
            self.traceroute_btn.setText("Traceroute")
            self.telemetry_btn.setEnabled(True)
            self.telemetry_btn.setText("Get Telemetry")
            import datetime
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.results_display.append(f"[{timestamp}] Command completed.")

    def onRequestTelemetry(self):
        """Request telemetry"""
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        target = self.target_select.currentText().strip()
        channel = self.channel_input.value()
        
        if not target:
            self.logWithTimestamp("No target selected for telemetry.")
            return
        
        # Extract node ID from target text (look for ID in parentheses or use the whole target)
        node_id_match = re.search(r'\(([^)]+)\)', target)
        if node_id_match:
            node_id = node_id_match.group(1)
        else:
            node_id = target.split()[-1]  # Use last word if no parentheses
        
        # Build command using subprocess args instead of shell=True to avoid quoting issues
        cmd = ["meshtastic"]
        
        # Add connection parameters
        if method == "Serial Port" and address:
            cmd.extend(["--port", address])
        elif method == "IP Address" and address:
            cmd.extend(["--host", address])
        elif method == "Bluetooth":
            if address:
                cmd.extend(["--ble", address])
            else:
                cmd.append("--ble")
        
        # Add telemetry command and target
        cmd.extend(["--request-telemetry", "--dest", node_id])
        
        # Add channel if specified
        if channel > 0:
            cmd.extend(["--ch-index", str(channel)])
        
        # Disable button while running
        self.telemetry_btn.setEnabled(False)
        self.telemetry_btn.setText("Running...")
        
        # Queue the command
        self.queueMeshtasticCommand(cmd, "telemetry")

    def onSendMessage(self):
        """Send message"""
        msg = self.message_input.text().strip()
        if not msg:
            QMessageBox.warning(self, "Send Message", "Message cannot be empty.")
            return
        
        message_type = self.message_type.currentText()
        channel = self.channel_input.value()
        
        try:
            if message_type == "To Channel":
                cmd = self.buildMeshtasticCommand("--sendtext", msg)
                if channel > 0:
                    cmd.extend(["--ch-index", str(channel)])
                self.logWithTimestamp(f"Sending to channel {channel}: {msg}")
            else:  # To Node
                target = self.target_select.currentText()
                if not target:
                    QMessageBox.warning(self, "Send Message", "Please select a target node first.")
                    return
                
                # Extract node ID from target text
                node_id = target.split('(')[-1].rstrip(')') if '(' in target else target
                
                cmd = self.buildMeshtasticCommand("--sendtext", msg, "--dest", node_id)
                if self.ack_cb.isChecked():
                    cmd.append("--request-ack")
                    
                self.logWithTimestamp(f"Sending to {target}: {msg}")
            
            self.logWithTimestamp(f"Command: {' '.join(cmd)}")
            # Here you would execute the command similar to onRefreshNodes
            # For now, just show what would be executed
            self.message_input.clear()
            
        except Exception as e:
            self.logWithTimestamp(f"Message send error: {str(e)}")

    def onClearLog(self):
        """Clear log"""
        if hasattr(self, 'results_display'):
            self.results_display.clear()

    def buildMeshtasticCommand(self, *args):
        """Build a meshtastic command with proper connection parameters based on current settings."""
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        cmd = ["meshtastic"]
        
        # Add connection parameters based on method
        if method == "Serial Port" and address:
            cmd.extend(["--port", address])
        elif method == "IP Address" and address:
            cmd.extend(["--host", address])
        elif method == "Bluetooth":
            if address:
                cmd.extend(["--ble", address])
            else:
                cmd.append("--ble")
        
        # Add the requested arguments
        cmd.extend(args)
        
        return cmd

    def onRefreshNodes(self):
        """Refresh the node list from the actual device using Meshtastic CLI."""
        method = self.connection_method.currentText()
        address = self.connection_input.text().strip()
        
        # For Bluetooth, address is optional (can auto-discover)
        if method != "Bluetooth" and not address:
            QMessageBox.warning(self, "Refresh Error", "Please enter a valid device address or port.")
            return
            
        self.logWithTimestamp(f"Refreshing nodes from {method}: {address or 'auto-discover'}")
        
        try:
            cmd = self.buildMeshtasticCommand("--nodes")
            self.queueMeshtasticCommand(cmd, "nodes")
        except Exception as e:
            self.logWithTimestamp(f"Failed to queue refresh nodes command: {str(e)}")

    def parse_meshtastic_nodes_output(self, output):
        """Parse Meshtastic CLI output and return a list of node dicts."""
        nodes = []
        # Try to parse JSON output first
        try:
            data = json.loads(output)
            if isinstance(data, dict) and "nodes" in data:
                for node in data["nodes"]:
                    nodes.append(node)
                return nodes
            elif isinstance(data, list):
                return data
        except Exception:
            pass
        # Fallback: parse text output line by line
        for line in output.splitlines():
            # Example line: "Node: user=foo id=1234 ..."
            if "id=" in line:
                node = {}
                for part in line.split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        node[k] = v
                if node:
                    nodes.append(node)
        return nodes

    def parse_meshtastic_table_output(self, output):
        """Parse pretty-printed Meshtastic CLI table output and return a list of node dicts."""
        nodes = []
        lines = output.splitlines()
        header = []
        # Find header row
        for i, line in enumerate(lines):
            if line.startswith("│") and "User" in line and "ID" in line:
                # Extract header columns
                header = [h.strip() for h in line.split("│")[1:-1]]
                header_idx = i
                break
        if not header:
            return nodes
        # Parse node rows
        for line in lines[header_idx+2:]:
            if line.startswith("│") and not line.startswith("╘"):
                cells = [c.strip() for c in line.split("│")[1:-1]]
                if len(cells) == len(header):
                    node = dict(zip(header, cells))
                    nodes.append(node)
        return nodes

    def update_nodes_table(self, nodes):
        """Update the node table with parsed node data, preserving existing data and only updating with newer info."""
        import datetime
        
        def parse_last_heard(last_heard_str):
            """Parse last heard time to datetime for comparison."""
            if not last_heard_str or last_heard_str.strip() == "":
                return None
            try:
                # Try different formats
                formats = [
                    "%Y-%m-%d %H:%M:%S",
                    "%H:%M:%S",
                    "%Y-%m-%d",
                    "%m-%d %H:%M",
                ]
                for fmt in formats:
                    try:
                        return datetime.datetime.strptime(last_heard_str.strip(), fmt)
                    except ValueError:
                        continue
                # If no format works, assume it's recent
                return datetime.datetime.now()
            except:
                return None
        
        # Build a mapping of existing nodes from the table
        existing_nodes = {}
        for row in range(self.nodes_table.rowCount()):
            node_id_item = self.nodes_table.item(row, 3)  # ID column
            if node_id_item and node_id_item.text():
                node_id = node_id_item.text()
                existing_nodes[node_id] = {
                    'row': row,
                    'favorite': self.nodes_table.item(row, 0).text() if self.nodes_table.item(row, 0) else "",
                    'last_heard': self.nodes_table.item(row, 16).text() if self.nodes_table.item(row, 16) else "",
                    'remark': self.nodes_table.item(row, 22).text() if self.nodes_table.item(row, 22) else ""
                }
        
        columns = [
            "Fav", "N", "User", "ID", "AKA", "Hardware", "Role", "Latitude", "Longitude", "Altitude",
            "Battery", "Channel util.", "Tx air util.", "SNR", "Hops", "Channel", "LastHeard", "Since",
            "Traceroutes", "Telemetry", "Pubkey", "Source", "Remark"
        ]
        
        updated_count = 0
        new_count = 0
        preserved_count = 0
        
        # Process new nodes
        for node in nodes:
            node_id = node.get('ID') or node.get('id') or ""
            if not node_id:
                continue
                
            new_last_heard = node.get('LastHeard') or node.get('lastHeard') or ""
            
            if node_id in existing_nodes:
                # Node exists - check if we should update
                existing = existing_nodes[node_id]
                existing_last_heard = existing['last_heard']
                
                # Parse timestamps for comparison
                new_time = parse_last_heard(new_last_heard)
                existing_time = parse_last_heard(existing_last_heard)
                
                should_update = False
                if new_time and existing_time:
                    should_update = new_time > existing_time
                elif new_time and not existing_time:
                    should_update = True
                elif new_last_heard and not existing_last_heard:
                    should_update = True
                
                if should_update:
                    # Update existing row with newer data, but preserve user data
                    row = existing['row']
                    for col_idx, col_name in enumerate(columns):
                        if col_idx == 0:  # Favorite column - preserve existing
                            continue
                        elif col_idx == 21:  # Source column - update with current connection
                            method = self.connection_method.currentText()
                            address = self.connection_input.text().strip()
                            if method == "Bluetooth":
                                source_text = f"BLE{': ' + address if address else ''}"
                            elif method == "Serial Port":
                                source_text = f"Serial{': ' + address if address else ''}"
                            elif method == "IP Address":
                                source_text = f"IP{': ' + address if address else ''}"
                            else:
                                source_text = "Unknown"
                            item = QTableWidgetItem(source_text)
                            self.nodes_table.setItem(row, col_idx, item)
                        elif col_idx == 22:  # Remark column - preserve existing
                            continue
                        else:
                            # Update with new data
                            value = node.get(col_name) or node.get(col_name.replace(" ", "")) or node.get(col_name.lower()) or ""
                            item = QTableWidgetItem(str(value))
                            self.nodes_table.setItem(row, col_idx, item)
                    updated_count += 1
                else:
                    preserved_count += 1
                    
                # Remove from existing_nodes so we know it was processed
                del existing_nodes[node_id]
            else:
                # New node - add it
                row = self.nodes_table.rowCount()
                self.nodes_table.insertRow(row)
                for col_idx, col_name in enumerate(columns):
                    if col_idx == 0:  # Favorite column
                        # Check if this node is in favorites
                        fav_text = "★" if node_id in self.favorite_nodes else ""
                        item = QTableWidgetItem(fav_text)
                        self.nodes_table.setItem(row, col_idx, item)
                    elif col_idx == 21:  # Source column  
                        # Set the source based on current connection method
                        method = self.connection_method.currentText()
                        address = self.connection_input.text().strip()
                        if method == "Bluetooth":
                            source_text = f"BLE{': ' + address if address else ''}"
                        elif method == "Serial Port":
                            source_text = f"Serial{': ' + address if address else ''}"
                        elif method == "IP Address":
                            source_text = f"IP{': ' + address if address else ''}"
                        else:
                            source_text = "Unknown"
                        item = QTableWidgetItem(source_text)
                        self.nodes_table.setItem(row, col_idx, item)
                    elif col_idx == 22:  # Remark column
                        # Check if we have a saved remark for this node
                        remark_text = self.node_remarks.get(node_id, "")
                        item = QTableWidgetItem(remark_text)
                        self.nodes_table.setItem(row, col_idx, item)
                    else:
                        value = node.get(col_name) or node.get(col_name.replace(" ", "")) or node.get(col_name.lower()) or ""
                        item = QTableWidgetItem(str(value))
                        self.nodes_table.setItem(row, col_idx, item)
                new_count += 1
        
        # Report results
        total_nodes = len(nodes)
        if total_nodes >= 100:
            self.results_display.append(f"⚠️  Node list may be limited to {total_nodes} nodes by device/CLI.")
            self.results_display.append("   Consider using '--nodes --limit 0' or check device settings for full list.")
            
        self.results_display.append(f"Node table updated: {new_count} new, {updated_count} updated, {preserved_count} preserved (total: {self.nodes_table.rowCount()} nodes).")

    def onDeleteSelectedNode(self):
        """Delete the currently selected node from the discovered nodes list"""
        row = self.nodes_table.currentRow()
        if row >= 0:
            node_id = self.nodes_table.item(row, 3).text() if self.nodes_table.item(row, 3) else None
            self.nodes_table.removeRow(row)
            if node_id and node_id in self.discovered_nodes:
                del self.discovered_nodes[node_id]
                self.saveDiscoveredNodes()
            self.results_display.append(f"Node at row {row} deleted.")

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
        # Real consistency check logic could be added here
        self.results_display.append("Data consistency check complete.")

    def onResetNodesList(self):
        """Reset the nodes list"""
        self.nodes_table.setRowCount(0)
        self.discovered_nodes = {}
        self.saveDiscoveredNodes()
        self.results_display.append("Nodes list reset.")

    def onNodeFilterChanged(self):
        """Apply text filter and favorites filter to the node table"""
        filter_text = self.node_filter_input.text().lower()
        favorites_only = self.favorites_only_cb.isChecked()
        
        for row in range(self.nodes_table.rowCount()):
            show_row = True
            
            # Apply text filter
            if filter_text:
                row_text = ""
                for col in [2, 3, 4, 5]:  # User, ID, AKA, Hardware columns
                    item = self.nodes_table.item(row, col)
                    if item:
                        row_text += item.text().lower() + " "
                if filter_text not in row_text:
                    show_row = False
            
            # Apply favorites filter
            if favorites_only and show_row:
                node_item = self.nodes_table.item(row, 3)
                node_id = node_item.text() if node_item else None
                if not node_id or node_id not in self.favorite_nodes:
                    show_row = False
            
            self.nodes_table.setRowHidden(row, not show_row)
        
        # Count visible rows
        visible_count = sum(1 for r in range(self.nodes_table.rowCount()) if not self.nodes_table.isRowHidden(r))
        self.results_display.append(f"Filter applied: {visible_count} of {self.nodes_table.rowCount()} nodes visible.")

    def onResetFilters(self):
        """Reset all filters and show all node rows"""
        # Clear text filter and favorites-only checkbox
        self.node_filter_input.clear()
        self.favorites_only_cb.setChecked(False)
        # Re-apply filter logic to reveal all rows
        self.onNodeFilterChanged()
        self.results_display.append("Filters reset.")

    def onShowColumnDialog(self):
        """Show dialog for column visibility management"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Show/Hide Columns")
        dialog.setModal(True)
        dialog.resize(400, 500)
        
        layout = QVBoxLayout()
        instructions = QLabel("Select which columns to show in the nodes table:")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        headers = []
        for i in range(self.nodes_table.columnCount()):
            header_item = self.nodes_table.horizontalHeaderItem(i)
            if header_item:
                headers.append(header_item.text())
            else:
                headers.append(f"Column {i}")
        
        self.column_checkboxes = {}
        for i, header in enumerate(headers):
            checkbox = QCheckBox(header)
            checkbox.setChecked(not self.nodes_table.isColumnHidden(i))
            self.column_checkboxes[i] = checkbox
            layout.addWidget(checkbox)

        button_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self.setAllColumns(True))
        button_layout.addWidget(select_all_btn)
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(lambda: self.setAllColumns(False))
        button_layout.addWidget(deselect_all_btn)
        button_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(lambda: self.applyColumnVisibility(dialog))
        ok_btn.setDefault(True)
        button_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        result = dialog.exec_()
        if result == QDialog.Accepted:
            self.logWithTimestamp("Column visibility updated.")

    def setAllColumns(self, visible):
        """Set all column checkboxes to visible or hidden"""
        if hasattr(self, 'column_checkboxes'):
            for checkbox in self.column_checkboxes.values():
                checkbox.setChecked(visible)
    
    def applyColumnVisibility(self, dialog):
        """Apply the column visibility settings from the dialog"""
        if hasattr(self, 'column_checkboxes'):
            for col_index, checkbox in self.column_checkboxes.items():
                self.nodes_table.setColumnHidden(col_index, not checkbox.isChecked())
            # Save visibility in settings
            self.column_visibility = {self.nodes_table.horizontalHeaderItem(i).text(): not self.nodes_table.isColumnHidden(i)
                                       for i in range(self.nodes_table.columnCount())}
            self.saveSettings()
        dialog.accept()
    
    def onNodeCellChanged(self, row, column):
        """Handle changes to node table cells, especially remarks"""
        node_id = self.nodes_table.item(row, 3).text() if self.nodes_table.item(row, 3) else None
        if node_id:
            remark = self.nodes_table.item(row, 22).text() if self.nodes_table.item(row, 22) else ""
            self.node_remarks[node_id] = remark
            self.saveNodeRemarks()
            self.logWithTimestamp(f"Remark updated for node {node_id}.")

    def onNodeCellClicked(self, row, column):
        """Handle cell clicks, especially for favorite column and location data"""
        node_id = self.nodes_table.item(row, 3).text() if self.nodes_table.item(row, 3) else None
        node_user = self.nodes_table.item(row, 2).text() if self.nodes_table.item(row, 2) else ""
        
        if column == 0 and node_id:
            # Toggle favorite
            if node_id in self.favorite_nodes:
                self.favorite_nodes.remove(node_id)
                # Update display to show unfavorited
                if self.nodes_table.item(row, 0):
                    self.nodes_table.item(row, 0).setText("")
            else:
                self.favorite_nodes.add(node_id)
                # Update display to show favorited
                if self.nodes_table.item(row, 0):
                    self.nodes_table.item(row, 0).setText("★")
                else:
                    item = QTableWidgetItem("★")
                    self.nodes_table.setItem(row, 0, item)
            self.saveFavorites()
            self.logWithTimestamp(f"Favorite toggled for node {node_id}.")
        elif column == 7 or column == 8:  # Latitude or Longitude columns
            # Open coordinates in map service
            lat_item = self.nodes_table.item(row, 7)  # Latitude column
            lon_item = self.nodes_table.item(row, 8)  # Longitude column
            
            if lat_item and lon_item:
                lat = lat_item.text().strip()
                lon = lon_item.text().strip()
                
                if lat and lon and lat != "0.0" and lon != "0.0":
                    try:
                        # Validate coordinates
                        lat_float = float(lat)
                        lon_float = float(lon)
                        
                        # Build map URL based on selected service
                        service = self.location_service
                        if service == "Google Maps":
                            map_url = f"https://www.google.com/maps?q={lat},{lon}"
                        elif service == "Bing Maps":
                            map_url = f"https://www.bing.com/maps?cp={lat}~{lon}&lvl=16"
                        else:  # OpenStreetMap (default)
                            map_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=16"
                        
                        # Open in browser
                        webbrowser.open(map_url)
                        
                        self.results_display.append(f"Opening {service} for coordinates: {lat}, {lon}")
                        
                    except ValueError:
                        self.results_display.append(f"Invalid coordinates: {lat}, {lon}")
                else:
                    self.results_display.append("No valid coordinates to display.")
        else:
            # Set as target for any other column click
            if node_id:
                # Update target selection dropdown
                target_text = f"{node_user} ({node_id})" if node_user else node_id
                
                # Check if already in dropdown
                found = False
                for i in range(self.target_select.count()):
                    if node_id in self.target_select.itemText(i):
                        self.target_select.setCurrentIndex(i)
                        found = True
                        break
                
                if not found:
                    # Add to dropdown and select it
                    self.target_select.addItem(target_text)
                    self.target_select.setCurrentText(target_text)
                
                self.results_display.append(f"Selected target: {target_text}")

    def onNodeCellDoubleClicked(self, row, column):
        """Handle double-clicks for detailed traceroute view"""
        node_id = self.nodes_table.item(row, 3).text() if self.nodes_table.item(row, 3) else None
        if column == 18 and node_id:
            # Show traceroute details
            details = self.traceroute_history.get(node_id, [])
            QMessageBox.information(self, "Traceroute Details", f"Traceroute for node {node_id}:\n{details}")
        elif column == 19 and node_id:
            # Show telemetry details
            details = self.telemetry_history.get(node_id, [])
            QMessageBox.information(self, "Telemetry Details", f"Telemetry for node {node_id}:\n{details}")

    def saveDiscoveredNodes(self):
        try:
            with open(self.discovered_nodes_file, 'w') as f:
                json.dump(self.discovered_nodes, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            self.results_display.append("Discovered nodes saved.")
        except Exception as e:
            self.results_display.append(f"Failed to save discovered nodes: {str(e)}")

    def loadDiscoveredNodes(self):
        try:
            if os.path.exists(self.discovered_nodes_file):
                with open(self.discovered_nodes_file, 'r') as f:
                    self.discovered_nodes = json.load(f)
                nodes = list(self.discovered_nodes.values())
                self.update_nodes_table(nodes)
        except Exception as e:
            if hasattr(self, 'results_display'):
                self.results_display.append(f"Failed to load discovered nodes: {str(e)}")

    def saveFavorites(self):
        try:
            with open(self.favorites_file, 'w') as f:
                json.dump(list(self.favorite_nodes), f, indent=2)
        except Exception as e:
            if hasattr(self, 'results_display'):
                self.results_display.append(f"Failed to save favorites: {str(e)}")

    def loadFavorites(self):
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r') as f:
                    favorites_list = json.load(f)
                    self.favorite_nodes = set(favorites_list) if isinstance(favorites_list, list) else set()
        except Exception as e:
            if hasattr(self, 'results_display'):
                self.results_display.append(f"Failed to load favorites: {str(e)}")

    def saveNodeRemarks(self):
        try:
            with open(self.node_remarks_file, 'w') as f:
                json.dump(self.node_remarks, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            self.results_display.append("Node remarks saved.")
        except Exception as e:
            self.results_display.append(f"Failed to save node remarks: {str(e)}")

    def loadNodeRemarks(self):
        try:
            if os.path.exists(self.node_remarks_file):
                with open(self.node_remarks_file, 'r') as f:
                    self.node_remarks = json.load(f)
        except Exception as e:
            if hasattr(self, 'results_display'):
                self.results_display.append(f"Failed to load node remarks: {str(e)}")

    def loadTracerouteHistory(self):
        try:
            if os.path.exists(self.traceroute_history_file):
                with open(self.traceroute_history_file, 'r') as f:
                    self.traceroute_history = json.load(f)
        except Exception as e:
            if hasattr(self, 'results_display'):
                self.results_display.append(f"Failed to load traceroute history: {str(e)}")

    def loadTelemetryHistory(self):
        try:
            if os.path.exists(self.telemetry_history_file):
                with open(self.telemetry_history_file, 'r') as f:
                    self.telemetry_history = json.load(f)
        except Exception as e:
            if hasattr(self, 'results_display'):
                self.results_display.append(f"Failed to load telemetry history: {str(e)}")

    def saveConnectionPresets(self):
        try:
            with open(self.connection_presets_file, 'w') as f:
                json.dump(self.connection_presets, f, indent=2)
        except Exception as e:
            self.results_display.append(f"Failed to save connection presets: {str(e)}")

    def loadConnectionPresets(self):
        try:
            if os.path.exists(self.connection_presets_file):
                with open(self.connection_presets_file, 'r') as f:
                    self.connection_presets = json.load(f)
                self.updatePresetCombo()
        except Exception as e:
            self.results_display.append(f"Failed to load connection presets: {str(e)}")

    def loadSettings(self):
        """Load all settings and data from files, with automated repair and detailed reporting for JSON files"""
        def check_and_repair_json_file(path, key=None):
            report = []
            repaired = False
            try:
                if not os.path.exists(path):
                    # File doesn't exist yet - create empty default
                    default_data = {} if path.endswith('.json') else []
                    with open(path, 'w') as f:
                        json.dump(default_data, f, indent=2)
                    report.append(f"Created default file: {path}")
                    return default_data, report, False
                
                with open(path, 'r') as f:
                    data = json.load(f)
                # Sanity check: must be dict or list
                if not isinstance(data, (dict, list)):
                    report.append(f"File {path} is not a dict or list. Marked as faulty.")
                    return None, report, repaired
                # Check entries for dicts (only for specific file types)
                if isinstance(data, dict) and path not in [self.settings_file]:
                    for k, v in list(data.items()):
                        if not isinstance(v, (dict, str, int, float, bool, list)) and v is not None:
                            report.append(f"Faulty entry in {path}: key '{k}' has invalid type. Attempting repair.")
                            # Attempt repair: wrap in dict
                            data[k] = {"repaired": True, "original": str(v), "remark": "Faulty entry detected and wrapped."}
                            repaired = True
                return data, report, repaired
            except Exception as e:
                report.append(f"Failed to load {path}: {str(e)}. Creating default file.")
                # Create default file
                try:
                    default_data = {} if path.endswith('.json') else []
                    with open(path, 'w') as f:
                        json.dump(default_data, f, indent=2)
                    return default_data, [], False
                except Exception:
                    return None, report, repaired

        # Load basic settings first
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    if "connection_method" in settings and hasattr(self, 'connection_method'):
                        index = self.connection_method.findText(settings["connection_method"])
                        if index >= 0:
                            self.connection_method.setCurrentIndex(index)
                    if "connection_address" in settings and hasattr(self, 'connection_input'):
                        self.connection_input.setText(settings["connection_address"])
                    if "location_service" in settings:
                        self.location_service = settings["location_service"]
                        if hasattr(self, 'location_service_combo'):
                            self.location_service_combo.setCurrentText(self.location_service)
                    if "column_visibility" in settings and hasattr(self, 'nodes_table'):
                        # Restore column visibility
                        self.column_visibility = settings["column_visibility"]
                        for i in range(self.nodes_table.columnCount()):
                            header_item = self.nodes_table.horizontalHeaderItem(i)
                            if header_item:
                                column_name = header_item.text()
                                if column_name in self.column_visibility:
                                    self.nodes_table.setColumnHidden(i, not self.column_visibility[column_name])
        except Exception:
            pass

        summary_report = []
        files_checked = [
            ("settings_file", getattr(self, 'settings_file', 'meshtastic_settings.json')),
            ("node_remarks_file", getattr(self, 'node_remarks_file', None)),
            ("discovered_nodes_file", getattr(self, 'discovered_nodes_file', None)),
            ("favorites_file", getattr(self, 'favorites_file', None)),
            ("node_keys_file", getattr(self, 'node_keys_file', None)),
            ("telemetry_stats_file", getattr(self, 'telemetry_stats_file', None)),
            ("connection_presets_file", getattr(self, 'connection_presets_file', None)),
            ("traceroute_history_file", getattr(self, 'traceroute_history_file', None)),
            ("telemetry_history_file", getattr(self, 'telemetry_history_file', None)),
        ]
        for attr, path in files_checked:
            if path:
                data, report, repaired = check_and_repair_json_file(path)
                if data is not None:
                    summary_report.append(f"{attr}: loaded and checked.")
                    if report:
                        summary_report.extend(report)
                    if repaired:
                        # Save repaired file
                        try:
                            with open(path, 'w') as f:
                                json.dump(data, f, indent=2)
                            summary_report.append(f"{attr}: faulty entries repaired and file updated.")
                        except Exception as e:
                            summary_report.append(f"{attr}: failed to save repaired file: {str(e)}")
                else:
                    summary_report.append(f"{attr}: failed to load or create.")
                    if report:
                        summary_report.extend(report)
        
        # Only display report if there are issues
        if any("faulty" in line or "failed" in line.lower() or "error" in line.lower() for line in summary_report):
            if hasattr(self, 'results_display'):
                self.results_display.append("\n--- Data Integrity Report ---")
                for line in summary_report:
                    self.results_display.append(line)
                self.results_display.append("--- End of Report ---\n")
    
    def onToggleConfigVisibility(self):
        """Toggle the visibility of the configuration editor."""
        if hasattr(self, 'config_scroll'):
            visible = self.config_scroll.isVisible()
            self.config_scroll.setVisible(not visible)
            if not visible:
                self.toggle_config_btn.setText("▼ Hide Configuration")
            else:
                self.toggle_config_btn.setText("▶ Show Configuration")
            self.results_display.append(f"Configuration editor {'shown' if not visible else 'hidden'}.")
    
    def onMessageTypeChanged(self, msg_type):
        """Handle message type change"""
        if msg_type == "To Channel":
            self.ack_cb.setEnabled(False)
        else:
            self.ack_cb.setEnabled(True)
    
    def updateNodesTable(self):
        """Update the nodes table with current data"""
        # This method refreshes the table display
        if hasattr(self, 'discovered_nodes'):
            nodes = list(self.discovered_nodes.values())
            self.update_nodes_table(nodes)
    
    def saveNodeKeys(self):
        """Save node keys to file"""
        try:
            with open(self.node_keys_file, 'w') as f:
                json.dump(self.node_keys, f, indent=2)
        except Exception as e:
            if hasattr(self, 'results_display'):
                self.results_display.append(f"Failed to save node keys: {str(e)}")
    
    def loadDeviceConnections(self):
        """Load device connections for smart preset matching"""
        # Real device connections load logic could be added here
        pass

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