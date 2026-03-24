import os
import sys
import threading
import traceback

_project_dir = os.path.dirname(__file__)
_scripts_dir = os.path.join(_project_dir, "scripts")
if _project_dir and _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
if _scripts_dir and _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

try:
    from scripts.task_exectutor_fun import task_exectutor
except Exception:
    from task_exectutor_fun import task_exectutor


class OrderBackend:
    def __init__(self, log_callback=None, base_log_dir=None):
        self.log_callback = log_callback
        self.base_log_dir = base_log_dir
        self.stop_event = threading.Event()
        self.is_running = False

    def log_message(self, message):
        cb = getattr(self, "log_callback", None)
        if cb:
            try:
                cb(str(message))
                return
            except Exception:
                pass
        try:
            print(str(message))
        except Exception:
            pass

    def run_manual_task(self, task_text, task_id=None):
        self.stop_event.clear()
        try:
            ret = task_exectutor(
                task_text=str(task_text),
                root_dir=self.base_log_dir,
                log_callback=self.log_message,
                stop_event=self.stop_event,
            )
            return ret
        except Exception as e:
            self.log_message(f"Task executor error: {e}\n{traceback.format_exc()}")
            raise

    def start_query_thread(self):
        self.log_message("Remote order querying has been removed in the open-source version.")

    def stop_query_thread(self):
        try:
            self.is_running = False
        except Exception:
            pass
        try:
            self.stop_event.set()
        except Exception:
            pass

    def get_users(self):
        return []

    def add_user(self, email, pwd):
        return False

    def add_user_with_login(self, email, pwd):
        return False, "Account-based login has been removed in the open-source version."

    def ensure_token(self, email, pwd):
        return False
