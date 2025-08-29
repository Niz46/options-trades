# uptime/apps.py
import os
import threading
import time
import requests
from django.apps import AppConfig
from django.conf import settings

_lock_path = "/tmp/.uptime_ping_lock"

class UptimeConfig(AppConfig):
    name = "uptime"

    def ready(self):
        # Only start one thread per *host* using a lockfile guard.
        # This avoids starting duplicate threads under the Django autoreloader
        # or multiple worker processes on the same container.
        try:
            # attempt to create a lock file atomically
            fd = os.open(_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            # another process already started the pinger
            return

        def self_ping():
            url = getattr(settings, "SELF_PING_URL", None)
            if not url:
                return

            # give the app a moment to finish startup
            time.sleep(10)

            while True:
                try:
                    # timeout small so we don't hang spawn
                    requests.get(url, timeout=5)
                except Exception:
                    # ignore transient failures
                    pass
                # ping every 7 minutes (less than 15m)
                time.sleep(420)

        thread = threading.Thread(target=self_ping, daemon=True)
        thread.start()
