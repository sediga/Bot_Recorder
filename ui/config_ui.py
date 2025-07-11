import ctypes
from sys import platform
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import shutil
import subprocess
import asyncio
from playwright.async_api import async_playwright

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")
CONFIG_FILE = os.path.join(CONFIG_DIR, "agent_config.json")
SETTINGS_LOCK_FILE = os.path.join(tempfile.gettempdir(), "botflows_settings.lock")

_settings_window = None  # Track if window is open


def find_chrome_executable():
    chrome_path = shutil.which("chrome") or shutil.which("chrome.exe")
    if chrome_path and os.path.exists(chrome_path):
        return chrome_path

    fallback_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in fallback_paths:
        if os.path.exists(path):
            return path

    return ""


def load_config():
    default = {
        "use_bundled_chrome": False,
        "chrome_path": ""
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                if not cfg.get("chrome_path"):
                    cfg["chrome_path"] = find_chrome_executable()
                return {**default, **cfg}
        except Exception:
            pass

    default["chrome_path"] = find_chrome_executable()
    return default


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def bring_window_to_front(window):
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = ctypes.windll.user32.GetForegroundWindow()

        # Get handle of our Tkinter window
        window.update_idletasks()
        handle = ctypes.windll.user32.GetParent(window.winfo_id())

        # Attach input to allow SetForegroundWindow
        thread_id = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(hwnd, 0)
        user32.AttachThreadInput(thread_id, fg_thread, True)

        SW_RESTORE = 9
        user32.ShowWindow(handle, SW_RESTORE)
        user32.SetForegroundWindow(handle)

        # Optional ALT key trick (simulate key press)
        user32.keybd_event(0x12, 0, 0, 0)  # ALT down
        user32.keybd_event(0x12, 0, 2, 0)  # ALT up

        user32.AttachThreadInput(thread_id, fg_thread, False)

    except Exception as e:
        print("Failed to bring to front:", e)

def open_config_ui(master):
    global _settings_window
    if _settings_window and _settings_window.winfo_exists():
        bring_window_to_front(_settings_window)
        return

    cfg = load_config()

    def save_and_close():
        global _settings_window
        cfg["use_bundled_chrome"] = chrome_var.get()
        cfg["chrome_path"] = chrome_path_var.get().strip()
        save_config(cfg)
        if os.path.exists(SETTINGS_LOCK_FILE):
            os.remove(SETTINGS_LOCK_FILE)
        _settings_window.destroy()
        _settings_window = None
        
    def clear_settings_window():
        global _settings_window
        _settings_window = None

    def browse_chrome():
        path = filedialog.askopenfilename(
            title="Select Chrome Executable",
            filetypes=[("Chrome Executable", "chrome.exe")]
        )
        if path:
            chrome_path_var.set(path)

    def test_chrome_launch():
        async def launch_browser():
            try:
                async with async_playwright() as p:
                    if chrome_var.get():  # use_bundled_chrome
                        browser = await p.chromium.launch(headless=False)
                        context = await browser.new_context()
                        page = await context.new_page()
                        await page.goto("https://example.com")
                        messagebox.showinfo(
                            "Bundled Chrome",
                            "Playwright Chromium launched.\nClose the browser window to continue."
                        )
                        await browser.close()
                    else:
                        chrome_path = chrome_path_var.get().strip()
                        if not chrome_path or not os.path.exists(chrome_path):
                            messagebox.showerror("Invalid Path", "Chrome path is empty or invalid.")
                            return

                        subprocess.Popen([
                            chrome_path,
                            "--no-first-run",
                            "--no-default-browser-check",
                            "--new-window",
                            "https://example.com"
                        ])
                        messagebox.showinfo("Real Chrome", "Chrome launched.\nCheck the new browser window.")
            except Exception as e:
                messagebox.showerror("Launch Failed", f"Failed to launch browser:\n{e}")

        asyncio.run(launch_browser())

    # ✅ Now using Toplevel(master), NOT Tk()
    _settings_window = tk.Toplevel(master)
    _settings_window.title("Botflows Agent Settings")
    _settings_window.grab_set()
    _settings_window.focus_set()

    chrome_var = tk.BooleanVar(value=cfg.get("use_bundled_chrome", True))
    chrome_path_var = tk.StringVar(value=cfg.get("chrome_path", ""))

    ttk.Label(_settings_window, text="Chrome Launch Mode", font=("Segoe UI", 10, "bold")).pack(pady=(15, 5))

    chrome_checkbox = ttk.Checkbutton(
        _settings_window,
        text="Use bundled Chromium (Playwright built-in)",
        variable=chrome_var
    )
    chrome_checkbox.pack(padx=20, pady=(0, 10))

    ttk.Label(_settings_window, text="Chrome Executable Path (for real Chrome):").pack(pady=(10, 5))
    path_frame = ttk.Frame(_settings_window)
    path_frame.pack(padx=20, fill='x')

    chrome_entry = ttk.Entry(path_frame, textvariable=chrome_path_var, width=50)
    chrome_entry.pack(side="left", fill="x", expand=True)

    ttk.Button(path_frame, text="Test", command=test_chrome_launch).pack(side="right", padx=(5, 0))
    ttk.Button(path_frame, text="Browse...", command=browse_chrome).pack(side="right", padx=(5, 0))

    ttk.Button(_settings_window, text="Save Settings", command=save_and_close).pack(pady=15)

    def on_close():
        global _settings_window
        if os.path.exists(SETTINGS_LOCK_FILE):
            os.remove(SETTINGS_LOCK_FILE)
        _settings_window.destroy()
        _settings_window = None

    _settings_window.protocol("WM_DELETE_WINDOW", on_close)


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()  # Keep root hidden
    open_config_ui(root)
    root.mainloop()
