# this is the main script for the pi camera control and communication with the arduino stepper controller and does the UI as well
import sys
import subprocess
import time
import os

running = True
CamControl = None
MeshBridge = None
try:
    CamControl = subprocess.Popen(['python3', '/home/gandalf/astro/Scripts/CamControl.py'], capture_output=True, text=True)
    MeshBridge = subprocess.Popen(['python3', '/home/gandalf/astro/Scripts/Main_Mesh_Bridge.py'], capture_output=True, text=True)
except CamControl.CalledProcessError as e:
    print(f"Camera Control process failed with error: {e.stderr}")
    running = False
except MeshBridge.CalledProcessError as e:
    print(f"Mesh Bridge process failed with error: {e.stderr}")
    running = False

while running == True:
    print("Camera Control Output:", CamControl.stdout)
    print("Mesh Bridge Output:", MeshBridge.stdout)
    try:
        cmd = sys.stdin.readline().strip()
    except Exception as e_rl:
        print(f"Error readline fallback: {e_rl}")
    parts = cmd.split()
    cmd_l = parts[0].lower()

    if cmd_l in ['target', 't'] and len(parts) > 1:
        target = parts[1].strip("'\"")
        try:
            MeshBridge.stdin.write(f'target {target}\n')
            MeshBridge.stdin.flush()
        except Exception as e_tc:
            print(f"Error sending target command to MeshBridge: {e_tc}")
    if cmd_l in ['capture', 'c', 's']:
        try:
            CamControl.stdin.write('capture\n')
            CamControl.stdin.flush()
        except Exception as e_cc:
            print(f"Error sending capture command to CamControl: {e_cc}")




    if cmd_l in ['exit', 'quit', 'q']:
        print("Exiting...")
        try:
            if CamControl:
                CamControl.terminate()
                CamControl.wait(timeout=2)
            if MeshBridge:
                MeshBridge.terminate()
                MeshBridge.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print("Child didn't exit gracefully, killing...")
            CamControl.kill()
            MeshBridge.kill()
        running = False

    time.sleep(0.01)

