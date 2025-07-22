import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json, os, threading, tempfile, shutil, asyncio, subprocess
from playwright.async_api import async_playwright


CONFIG_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(CONFIG_DIR, "../agent_config.json")
SETTINGS_LOCK_FILE = os.path.join(tempfile.gettempdir(), "botflows_settings.lock")


def load_config():
    default = {
        "use_bundled_chrome": False,
        "chrome_path": ""
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                return {**default, **cfg}
        except:
            pass
    return default


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def open_config_ui():
    if os.path.exists(SETTINGS_LOCK_FILE):
        print("Already open")
        return

    def show_window():
        with open(SETTINGS_LOCK_FILE, "w") as f:
            f.write("lock")

        root = tk.Tk()
        root.title("Botflows Agent Settings")

        cfg = load_config()
        chrome_var = tk.BooleanVar(master=root, value=cfg.get("use_bundled_chrome", True))
        chrome_path_var = tk.StringVar(master=root, value=cfg.get("chrome_path", ""))

        def save_and_close():
            cfg["use_bundled_chrome"] = chrome_var.get()
            cfg["chrome_path"] = chrome_path_var.get().strip()
            save_config(cfg)
            cleanup()

        def cleanup():
            try:
                root.destroy()
            except:
                pass
            if os.path.exists(SETTINGS_LOCK_FILE):
                os.remove(SETTINGS_LOCK_FILE)

        def browse_chrome():
            path = filedialog.askopenfilename(
                title="Select Chrome Executable",
                filetypes=[("Chrome Executable", "*.exe")]
            )
            if path:
                chrome_path_var.set(path)

        def test_chrome_launch():
            async def launch_browser():
                try:
                    async with async_playwright() as p:
                        if chrome_var.get():
                            browser = await p.chromium.launch(headless=False)
                            context = await browser.new_context()
                            page = await context.new_page()
                            await page.goto("https://example.com")
                            messagebox.showinfo("Success", "Bundled Chromium launched.")
                            await browser.close()
                        else:
                            chrome_path = chrome_path_var.get().strip()
                            if not chrome_path or not os.path.exists(chrome_path):
                                messagebox.showerror("Invalid Path", "Chrome path is invalid.")
                                return
                            subprocess.Popen([
                                chrome_path,
                                "--no-first-run",
                                "--no-default-browser-check",
                                "--new-window",
                                "https://example.com"
                            ])
                            messagebox.showinfo("Success", "Chrome launched.")
                except Exception as e:
                    messagebox.showerror("Error", f"Launch failed:\n{e}")

            threading.Thread(target=lambda: asyncio.run(launch_browser()), daemon=True).start()

        root.protocol("WM_DELETE_WINDOW", cleanup)

        ttk.Label(root, text="Chrome Launch Mode").pack(pady=(10, 5))
        ttk.Checkbutton(root, text="Use bundled Chromium", variable=chrome_var).pack()

        ttk.Label(root, text="Chrome Executable Path:").pack(pady=(10, 5))
        entry_frame = ttk.Frame(root)
        entry_frame.pack(padx=10, fill="x")

        ttk.Entry(entry_frame, textvariable=chrome_path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(entry_frame, text="Browse", command=browse_chrome).pack(side="left", padx=(5, 0))
        ttk.Button(entry_frame, text="Test", command=test_chrome_launch).pack(side="left", padx=(5, 0))

        ttk.Button(root, text="Save & Close", command=save_and_close).pack(pady=15)

        try:
            root.mainloop()
        finally:
            del chrome_var
            del chrome_path_var

    threading.Thread(target=show_window, daemon=True).start()
