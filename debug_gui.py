#!/usr/bin/env python3
import sys
print("Starting debug GUI...")
print(f"Python version: {sys.version}")

try:
    from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
    from PyQt5.QtCore import Qt
    print("PyQt5 imports successful")
    
    app = QApplication(sys.argv)
    print("QApplication created")
    
    # Create a simple window
    window = QWidget()
    window.setWindowTitle("DEBUG - Meshtastic GUI Test")
    window.setGeometry(100, 100, 400, 200)
    
    layout = QVBoxLayout()
    label = QLabel("Wenn du dieses Fenster siehst, funktioniert PyQt5!")
    label.setAlignment(Qt.AlignCenter)
    layout.addWidget(label)
    
    window.setLayout(layout)
    
    print("Window created, showing now...")
    window.show()
    print("Window.show() called")
    
    # Make sure window is visible
    window.raise_()
    window.activateWindow()
    print("Window raised and activated")
    
    print("Starting event loop...")
    sys.exit(app.exec_())
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
