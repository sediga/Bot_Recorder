import subprocess
import threading
import time
import webbrowser
import os
import sys

def resource_path(relative_path):
    # Gets absolute path to resource, works for dev and for PyInstaller
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def run_server():
    api_path = resource_path("api_server.py")
    subprocess.Popen([sys.executable, api_path])

def launch_ui():
    time.sleep(2)
    webbrowser.open("http://localhost:8000/docs")

if __name__ == "__main__":
    threading.Thread(target=run_server).start()
    launch_ui()
