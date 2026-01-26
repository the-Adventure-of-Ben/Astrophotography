"""
asi_helper.py
Safe wrapper for ZWO ASI cameras using zwoasi on Raspberry Pi.
Handles initialization, connection retries, and disconnections.
"""

import zwoasi # type: ignore
import time
import threading
import os
from serial.tools import list_ports # type: ignore

# Path to the shared library
SDK_PATH = "/usr/local/lib/libASICamera2.so"

# Initialize SDK once
def init_sdk():
    """Initialize the ZWO ASI SDK safely."""
    if not os.path.exists(SDK_PATH):
        raise FileNotFoundError(f"ASI SDK library not found at {SDK_PATH}")
    try:
        zwoasi.init(SDK_PATH)
    except Exception as e:
        print(f"⚠️ Failed to initialize ASI SDK: {e}")
        raise
    # print("✅ ASI SDK initialized.")

def Gui_Available():
    display = "DISPLAY" in os.environ
    if display:
        return display
    else:
        return False


# Get list of cameras safely
def list_cameras():
    """Return list of connected ZWO camera names."""
    try:
        return zwoasi.list_cameras()
    except zwoasi.ZWO_IOError:
        return []

def connect_camera(retries=5, delay=2):
    """Try to connect to the first available camera."""
    for attempt in range(1, retries + 1):
        cams = list_cameras()
        if cams:
            try:
                cam = zwoasi.Camera(cams[0])
               # print(f"✅ Connected to {cams[0]}")
                return cam
            except zwoasi.ZWO_IOError as e:
                print(f"⚠️ Camera not ready ({e}), retrying ({attempt}/{retries})…")
        else:
            print(f"⚠️ No camera detected ({attempt}/{retries})…")
        time.sleep(delay)
    print("❌ Could not connect to any ZWO camera.")
    return None

def monitor_camera(callback, interval=3):
    """
    Background monitor that calls `callback(connected: bool)` when camera status changes.
    Example:
        monitor_camera(lambda connected: print('Camera connected' if connected else 'Camera removed'))
    """
    def _monitor():
        last_state = None
        while True:
            connected = bool(list_cameras())
            if connected != last_state:
                callback(connected)
                last_state = connected
            time.sleep(interval)
    thread = threading.Thread(target=_monitor, daemon=True)
    thread.start()
    return thread

# Initialize SDK automatically when imported
try:
    init_sdk()
except Exception as e:
    print(f"⚠️ SDK initialization issue: {e}")

def find_rp2040(vid, pid, serial=None):
    for attempt in range(1, 6):   
        for p in list_ports.comports():
            if (p.vid == vid and p.pid == pid ) and (serial is None or p.serial_number == serial):
               # print(f"✅ Found RP2040 device at {p.device}")
                return p.device
        print("⚠️ No RP2040 device found.")
        time.sleep(2)
        attempt += 1
        if attempt > 5:
            print("❌ Could not find RP2040 device after multiple attempts.")
            return None