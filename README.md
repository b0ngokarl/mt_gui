# Meshtastic Client GUI

A full-featured PyQt5 GUI for managing Meshtastic mesh network devices, with persistent storage, real device communication, and robust automated testing.

## Features
- **Device Management:** Connect via Serial, IP, or Bluetooth; save/load connection presets; reboot and kill Meshtastic processes.
- **Configuration:** Load, save, reset device configuration; toggle config editor visibility.
- **Actions:** Traceroute, telemetry requests, send messages (to channel or node, with optional ACK).
- **Node List:**
  - Discover nodes from device (via Meshtastic CLI)
  - Persistent storage of discovered nodes, remarks, favorites, keys, telemetry, traceroutes
  - Filter/search nodes, show/hide columns, export to CSV
  - Mark favorites, edit remarks, view traceroute/telemetry details
  - Data integrity checks and automated repair for JSON files
- **Persistent Data:** All user and device data stored in JSON files, auto-repaired if corrupted.
- **Automated Testing:**
  - Shell script (`run_full_gui_tests.sh`) for running all tests and checking file validity
  - Python test harness (`test_full_gui_pyqt.py`) using `pytest` and `pytest-qt` for GUI feature coverage
  - Tests always reflect current client features

## Installation
1. **Dependencies:**
   - Python 3.13+
   - PyQt5
   - Meshtastic CLI
   - `pytest` and `pytest-qt` (for testing)

2. **Install PyQt5 and Meshtastic CLI:**
   ```bash
   pip install pyqt5 meshtastic
   ```

3. **Install Testing Tools:**
   ```bash
   pip install pytest pytest-qt
   ```
   > Note: `pytest-qt` must be installed via pip (no apt package).

## Usage
- Run the GUI:
  ```bash
  python meshtastic_gui.py
  ```
- Run all automated tests:
  ```bash
  ./run_full_gui_tests.sh
  ```
- Run the Python test harness:
  ```bash
  pytest test_full_gui_pyqt.py
  ```

## Data Files
- All persistent data is stored in JSON files:
  - `meshtastic_settings.json`, `node_remarks.json`, `discovered_nodes.json`, `favorites.json`, `node_keys.json`, `telemetry_stats.json`, `connection_presets.json`, `traceroute_history.json`, `telemetry_history.json`
- Data integrity is checked and auto-repaired on load; detailed reports shown in the GUI.

## Development & Testing
- All features are covered by automated tests.
- To keep tests in sync with the client, expand `test_full_gui_pyqt.py` as new features are added.
- Use the shell script for quick health checks after major changes.

## Automated Test Harness for AI Agents

This project includes a comprehensive automated test harness (`test_full_gui_pyqt.py`) using `pytest` and `pytest-qt` to ensure all GUI features are always covered and in sync with the real client. This harness:
- Instantiates the full GUI and verifies all major components and buttons
- Simulates user actions (preset save/load, connect/disconnect, refresh nodes, export CSV, reset nodes, remarks, favorites, data consistency checks)
- Validates persistent storage and GUI state after each action
- Can be expanded automatically as new features are added
- Is designed for use by AI agents and CI/CD bots to guarantee feature coverage and health

**How to use for AI/automation:**
- Run `pytest test_full_gui_pyqt.py` after any major code change
- Ensure all tests pass for production readiness
- Expand the test harness as new GUI features are added
- Use the shell script (`run_full_gui_tests.sh`) for full health checks

This section ensures that any AI or automation system can reliably keep the test suite in sync with the client and verify all features are covered.

## Contributing
- PRs welcome! Please ensure new features are reflected in the test harness and shell script.

## License
MIT

---

*Last Updated: July 2025 | Version: Production-ready with full automated testing and data integrity system*
