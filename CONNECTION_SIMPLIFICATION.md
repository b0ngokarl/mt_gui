# GUI Simplification: Removed Connect/Disconnect Buttons

## Changes Made

### 1. Removed Connection Management Buttons
- **Removed**: Connect and Disconnect buttons from the GUI
- **Reason**: Meshtastic CLI handles connections automatically based on parameters
- **Benefit**: Simplified interface, no manual connection state management needed

### 2. Always-Enabled Reboot Button
- **Before**: Reboot button was disabled until "connected"
- **After**: Reboot button is always enabled
- **Implementation**: Uses `buildMeshtasticCommand("--reboot")` to send reboot via CLI

### 3. Streamlined Button Layout
The connection settings now only show essential controls:
- **Save**: Save current settings to JSON
- **Load**: Load settings from file
- **Reboot**: Reboot device using CLI (always available)
- **Kill All**: Kill all meshtastic processes (emergency cleanup)

### 4. Updated Reboot Functionality
```python
def onReboot(self):
    """Reboot device using Meshtastic CLI"""
    cmd = self.buildMeshtasticCommand("--reboot")
    # Execute command and show output
```

### 5. Removed Connection State Logic
- No more button enable/disable based on connection status
- No more tracking of "connected" vs "disconnected" state
- CLI handles connection automatically for each command

## User Experience Improvements

### Simplified Workflow
1. **Set Connection Parameters**: Choose method (Serial/IP/Bluetooth) and address
2. **Use Any Function**: All functions work immediately without "connecting"
3. **CLI Handles Everything**: Each operation connects, executes, and disconnects automatically

### Always-Ready Operations
- **Refresh Nodes**: `meshtastic --ble --nodes` (works immediately)
- **Send Messages**: `meshtastic --ble --sendtext "message"` (works immediately)  
- **Reboot Device**: `meshtastic --ble --reboot` (works immediately)
- **Traceroute**: `meshtastic --ble --traceroute !nodeID` (works immediately)

### Benefits
1. **No Connection State Confusion**: Can't get "stuck" in connected/disconnected state
2. **Instant Operations**: All functions available immediately
3. **CLI Reliability**: Uses official CLI connection handling
4. **Cleaner Interface**: Fewer buttons, less complexity
5. **Always Fresh Connections**: Each operation uses current parameters

## Technical Implementation

### Before (Connection-Based)
```
1. Set connection parameters
2. Click "Connect" button 
3. Wait for connection confirmation
4. Use functions (if connected)
5. Click "Disconnect" when done
```

### After (Direct CLI)
```
1. Set connection parameters
2. Use any function directly
3. CLI connects automatically for each operation
```

### Command Examples
All operations now work the same way:
- **Bluetooth**: `meshtastic --ble --nodes`
- **Serial**: `meshtastic --port /dev/ttyUSB0 --nodes`  
- **IP**: `meshtastic --host 192.168.1.100 --nodes`

The GUI is now much simpler and more reliable, letting the Meshtastic CLI do what it does best - handle connections automatically!
