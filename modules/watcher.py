# modules/watcher.py
import os

WATCHDOG_AVAILABLE = False
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    # Watchdog not installed — fallback disabled
    class FileSystemEventHandler:
        pass


class FolderWatchHandler(FileSystemEventHandler):
    def __init__(self, queue):
        super().__init__()
        self._q = queue

    def on_created(self, event):
        if not event.is_directory:
            self._q.put(event.src_path)

