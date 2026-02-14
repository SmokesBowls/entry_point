import os
import subprocess
import socket
from pathlib import Path

def test_barriers():
    print("--- Starting Unsafe Tests ---")
    
    # 1. Test Filesystem Write
    try:
        print("Testing FS Write...")
        with open("blocked_file.txt", "w") as f:
            f.write("This should be blocked")
        print("❌ FS Write Error: Allowed unexpectedly")
    except RuntimeError as e:
        print(f"✅ FS Write: {e}")
    except Exception as e:
        print(f"❓ FS Write Unexpected Error: {type(e).__name__}: {e}")

    # 2. Test Subprocess
    try:
        print("Testing Subprocess...")
        subprocess.run(["echo", "hi"], capture_output=True)
        print("❌ Subprocess Error: Allowed unexpectedly")
    except RuntimeError as e:
        print(f"✅ Subprocess: {e}")

    # 3. Test Network
    try:
        print("Testing Network...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("google.com", 80))
        print("❌ Network Error: Allowed unexpectedly")
    except RuntimeError as e:
        print(f"✅ Network: {e}")

    # 4. Test os.system
    try:
        print("Testing os.system...")
        os.system("echo hi")
        print("❌ os.system Error: Allowed unexpectedly")
    except RuntimeError as e:
        print(f"✅ os.system: {e}")

if __name__ == "__main__":
    test_barriers()
