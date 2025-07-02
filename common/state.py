# common/state.py

is_recording = False
is_running = False
is_replaying = False
current_url = None
active_page = None
active_dom_snapshot = None
# Already has: is_running, is_recording, is_replaying, etc.
pick_mode = False
connections = []
worker_task = None  # Holds the worker task during recording
