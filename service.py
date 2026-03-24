import os
import time
import threading
from os import environ

if os.environ.get("ANDROID_PRIVATE"):
    os.environ.setdefault("KIVY_HOME", os.path.join(os.environ["ANDROID_PRIVATE"], ".kivy"))

os.environ.setdefault("FORCE_IPV4", "1")

try:
    from jnius import autoclass

    Context = autoclass("android.content.Context")
    PowerManager = autoclass("android.os.PowerManager")
    NotificationManager = autoclass("android.app.NotificationManager")
    NotificationChannel = autoclass("android.app.NotificationChannel")
    Build_VERSION = autoclass("android.os.Build$VERSION")
    AndroidRDrawable = autoclass("android.R$drawable")
except Exception:
    autoclass = None

NOTIFICATION_ID = 1
CHANNEL_ID = "appagent_service_channel"
CHANNEL_NAME = "AppAgent Service"


def _try_create_notification_channel():
    if not autoclass:
        return
    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        if service is None:
            return
        notification_manager = service.getSystemService(Context.NOTIFICATION_SERVICE)
        sdk_int = int(getattr(Build_VERSION, "SDK_INT", 0) or 0)
        if sdk_int >= 26:
            channel = NotificationChannel(CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_LOW)
            channel.setDescription("Background service for AppAgent tasks")
            notification_manager.createNotificationChannel(channel)
    except Exception:
        return


def _try_start_foreground_service():
    if not autoclass:
        return False
    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        if service is None:
            return False

        sdk_int = int(getattr(Build_VERSION, "SDK_INT", 0) or 0)
        try:
            small_icon = int(getattr(service.getApplicationInfo(), "icon", 0) or 0)
        except Exception:
            small_icon = 0
        if not small_icon:
            small_icon = int(getattr(AndroidRDrawable, "ic_dialog_info", 0) or 0)

        builder = autoclass("android.app.Notification$Builder")
        if sdk_int >= 26:
            n = builder(service, CHANNEL_ID)
        else:
            n = builder(service)
        n.setContentTitle("AppAgent")
        n.setContentText("Running in background...")
        n.setSmallIcon(small_icon)
        n.setOngoing(True)
        n.setAutoCancel(False)
        service.startForeground(NOTIFICATION_ID, n.build())
        return True
    except Exception:
        return False


class BackgroundService:
    def __init__(self):
        self.is_running = False
        self.service_thread = None
        self.log_callback = None
        self._wake_lock = None

    def set_backend(self, backend):
        return

    def log_message(self, message):
        if self.log_callback:
            try:
                self.log_callback(str(message))
                return
            except Exception:
                pass
        try:
            print(f"[Service] {message}")
        except Exception:
            pass

    def _ensure_wake_lock(self):
        if not os.environ.get("ANDROID_PRIVATE"):
            return
        if not autoclass:
            return
        if getattr(self, "_wake_lock", None):
            try:
                if self._wake_lock.isHeld():
                    return
            except Exception:
                pass
        try:
            PythonService = autoclass("org.kivy.android.PythonService")
            service = PythonService.mService
            if service is None:
                return
            power_manager = service.getSystemService(Context.POWER_SERVICE)
            wake_lock = power_manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "AppAgent:WakeLock")
            wake_lock.setReferenceCounted(False)
            wake_lock.acquire()
            self._wake_lock = wake_lock
        except Exception:
            return

    def _release_wake_lock(self):
        wl = getattr(self, "_wake_lock", None)
        if not wl:
            return
        try:
            if wl.isHeld():
                wl.release()
        except Exception:
            pass
        self._wake_lock = None

    def start_service(self, log_callback=None):
        if self.is_running:
            return
        self.log_callback = log_callback
        self.is_running = True

        if os.environ.get("ANDROID_PRIVATE"):
            _try_create_notification_channel()
            _try_start_foreground_service()
            self._ensure_wake_lock()

        self.service_thread = threading.Thread(target=self._run_service, daemon=True)
        self.service_thread.start()
        self.log_message("Background service started")

    def stop_service(self):
        if not self.is_running:
            return
        self.is_running = False
        try:
            if self.service_thread:
                self.service_thread.join(timeout=3)
        except Exception:
            pass
        self._release_wake_lock()
        self.log_message("Background service stopped")

    def _run_service(self):
        try:
            while self.is_running:
                time.sleep(1)
        finally:
            self.is_running = False
            self._release_wake_lock()


_service_instance = None


def get_service():
    global _service_instance
    if _service_instance is None:
        _service_instance = BackgroundService()
    return _service_instance


if __name__ == "__main__":
    argument = environ.get("PYTHON_SERVICE_ARGUMENT", "")
    print(f'service.py was successfully called with argument: "{argument}"')
    svc = get_service()
    svc.start_service()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        svc.stop_service()

