import os
import subprocess
import sys
import tkinter.messagebox as mbox
import api_server
import recorder
import common

PYTHON_EXEC = sys.executable  # Use the bundled Python interpreter

def ensure_pip():
    try:
        print(f"Running pip... {PYTHON_EXEC}")
        subprocess.run([PYTHON_EXEC, "-m", "pip", "--version"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"PIP not installed... {e}")
        subprocess.run([PYTHON_EXEC, "-m", "ensurepip", "--default-pip"], check=True)
        subprocess.run([PYTHON_EXEC, "-m", "pip", "install", "--upgrade", "pip"], check=True)

def install_dependencies():
    print("Upgrading pip...")
    subprocess.run([PYTHON_EXEC, "-m", "pip", "install", "--upgrade", "pip"], check=True)
    print("Installing playwright...")
    subprocess.run([PYTHON_EXEC, "-m", "pip", "install", "playwright==1.52.0"], check=True)
    print("Installing FastAPI & Uvicorn...")
    subprocess.run([PYTHON_EXEC, "-m", "pip", "install", "fastapi", "uvicorn"], check=True)
    print("Installing Chrome...")
    subprocess.run([PYTHON_EXEC, "-m", "playwright", "install", "chromium"], check=True)

def run_agent():
    print("Launching agent...")
    subprocess.Popen([PYTHON_EXEC, "api_server.py"], cwd=os.path.dirname(__file__))

def main():
    try:
        mbox.showinfo("Botflows Agent", "Installing dependencies — please wait...")
        ensure_pip()
        install_dependencies()
        run_agent()
        mbox.showinfo("Botflows Agent", "Agent is running. You can close this window.")
    except Exception as e:
        mbox.showerror("Botflows Agent - Error", f"Setup failed: {e}")

if __name__ == "__main__":
    main()
