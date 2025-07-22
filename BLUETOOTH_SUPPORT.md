# Bluetooth Command Support Enhancement

## Changes Made

### 1. Updated Command Builder for Bluetooth
- **Problem**: Bluetooth connections were using generic `meshtastic --nodes` instead of proper BLE format
- **Solution**: Added proper `--ble` parameter support for Bluetooth connections

### 2. New Helper Method: `buildMeshtasticCommand()`
- **Purpose**: Centralized command building for consistent meshtastic CLI usage
- **Benefits**: 
  - Ensures all operations use correct connection parameters
  - Easy to maintain and update
  - Consistent command format across all functions

### 3. Bluetooth Command Formats
Now generates proper commands based on connection type:

| Connection Type | Command Format | Example |
|----------------|----------------|---------|
| Serial Port | `meshtastic --port /dev/ttyUSB0 --nodes` | Port-specific |
| IP Address | `meshtastic --host 192.168.1.100 --nodes` | Network connection |
| Bluetooth | `meshtastic --ble --nodes` | Auto-discover |
| Bluetooth (specific) | `meshtastic --ble 00:11:22:33:44:55 --nodes` | Specific device |

### 4. Enhanced Node Refresh for Bluetooth
- **Auto-discovery**: Bluetooth can work without specifying an address
- **Optional Address**: Can specify specific Bluetooth MAC if needed
- **Proper Error Handling**: Only requires address for Serial/IP, not Bluetooth

### 5. Updated Action Methods
Enhanced the following methods to use proper Bluetooth commands:
- `onRefreshNodes()`: Node list refresh
- `onTraceroute()`: Traceroute operations  
- `onRequestTelemetry()`: Telemetry requests
- `onSendMessage()`: Message sending (channel and direct)

### 6. Command Examples
The GUI now generates commands like:

**Refresh Nodes:**
- Serial: `meshtastic --port /dev/ttyUSB0 --nodes`
- IP: `meshtastic --host 192.168.1.100 --nodes`
- **Bluetooth: `meshtastic --ble --nodes`** ✓

**Send Message:**
- To Channel: `meshtastic --ble --sendtext "Hello mesh!" --ch-index 0`
- To Node: `meshtastic --ble --sendtext "Direct message" --dest !12345678`

**Traceroute:**
- `meshtastic --ble --traceroute !12345678`

**Telemetry:**
- `meshtastic --ble --request-telemetry !12345678`

## User Experience Improvements

1. **Bluetooth Auto-Discovery**: No need to enter MAC address for basic operations
2. **Proper Command Generation**: All operations now use correct BLE parameters
3. **Command Visibility**: Shows exact command being executed for debugging
4. **Consistent Interface**: All connection types work the same way in the GUI

## Usage Instructions

### For Bluetooth Connections:
1. Select "Bluetooth" from the connection method dropdown
2. **Optional**: Enter specific Bluetooth MAC address, or leave blank for auto-discovery
3. Click "Refresh Nodes" - will use `meshtastic --ble --nodes`
4. All other operations (traceroute, telemetry, messaging) will automatically use `--ble`

### Backward Compatibility:
- Serial Port and IP Address connections work exactly as before
- Existing presets and settings are preserved
- No changes to the GUI interface

The GUI now properly supports the Meshtastic CLI's Bluetooth interface with the correct `--ble` parameter!
