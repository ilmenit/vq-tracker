
import sys
try:
    import sounddevice as sd
    print("sounddevice imported successfully")
    print(f"sounddevice version: {sd.__version__}")
    try:
        devices = sd.query_devices()
        print("Devices found:")
        print(devices)
    except Exception as e:
        print(f"Error querying devices: {e}")
except ImportError as e:
    print(f"Failed to import sounddevice: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
