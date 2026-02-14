import dependency_a
import os
import socket

print("Running relational_verify.py")

# 1. Trigger Mock Write
print("Attempting to write to restricted_file.txt...")
try:
    with open("restricted_file.txt", "w") as f:
        f.write("This should be mocked.")
    print("  ✅ Write call finished (Mocked)")
except Exception as e:
    print(f"  ❌ Write failed: {e}")

# 2. Trigger Mock Network
print("Attempting to connect to external domain...")
try:
    s = socket.socket()
    s.connect(("google.com", 80))
    print("  ✅ Connect call finished (Mocked)")
except Exception as e:
    print(f"  ❌ Connect failed: {e}")

# 3. Trigger Permitted Write (via allowlist.yml)
print("Attempting to write to /tmp/permitted.txt...")
try:
    with open("/tmp/permitted.txt", "w") as f:
        f.write("This should be allowed.")
    print("  ✅ Permitted write finished")
except Exception as e:
    print(f"  ❌ Permitted write failed: {e}")
