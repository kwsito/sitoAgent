import json
import os
import time
from kivy.clock import Clock
from kivy.utils import platform
from jnius import autoclass, PythonJavaClass, java_method

try:
    from android.runnable import run_on_ui_thread
except Exception:
    def run_on_ui_thread(f):
        return f


class _VoskListener(PythonJavaClass):
    __javainterfaces__ = ["org/vosk/android/RecognitionListener"]
    __javacontext__ = "app"

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def _emit(self, event_type, data):
        Clock.schedule_once(lambda dt: self._callback(event_type, data), 0)

    def _extract(self, hypothesis, key):
        try:
            return json.loads(hypothesis).get(key, "")
        except Exception:
            return ""

    @java_method("(Ljava/lang/String;)V")
    def onPartialResult(self, hypothesis):
        text = self._extract(hypothesis, "partial")
        if text:
            self._emit("PARTIAL", text)

    @java_method("(Ljava/lang/String;)V")
    def onResult(self, hypothesis):
        text = self._extract(hypothesis, "text")
        self._emit("RESULT", text)

    @java_method("(Ljava/lang/String;)V")
    def onFinalResult(self, hypothesis):
        text = self._extract(hypothesis, "text")
        self._emit("RESULT", text)

    @java_method("(Ljava/lang/Exception;)V")
    def onError(self, exception):
        self._emit("ERROR", str(exception))

    @java_method("()V")
    def onTimeout(self):
        self._emit("ERROR", "Timeout")


class _VoskStorageModelCallback(PythonJavaClass):
    __javainterfaces__ = ["org/vosk/android/StorageService$Callback"]
    __javacontext__ = "app"

    def __init__(self, manager):
        super().__init__()
        self._manager = manager

    @java_method("(Ljava/lang/Object;)V")
    def onComplete(self, model):
        self._manager.model = model
        self._manager.is_loaded = True
        self._manager.is_loading = False
        self._manager.callback("VOSK_READY", "Model Loaded")
        self._manager._log("model ready")

    @java_method("(Ljava/lang/Exception;)V")
    def onError(self, exception):
        self._manager.is_loading = False
        self._manager.callback("VOSK_ERROR", str(exception))
        self._manager._log(f"model error: {exception}")


class _VoskStorageErrorCallback(PythonJavaClass):
    __javainterfaces__ = ["org/vosk/android/StorageService$Callback"]
    __javacontext__ = "app"

    def __init__(self, manager):
        super().__init__()
        self._manager = manager

    @java_method("(Ljava/lang/Object;)V")
    def onComplete(self, exception):
        self._manager.is_loading = False
        self._manager.callback("VOSK_ERROR", str(exception))
        self._manager._log(f"io error complete: {exception}")

    @java_method("(Ljava/lang/Exception;)V")
    def onError(self, exception):
        self._manager.is_loading = False
        self._manager.callback("VOSK_ERROR", str(exception))
        self._manager._log(f"io error: {exception}")


class VoskManager:
    def __init__(self, model_asset_name, callback):
        self.model_asset_name = model_asset_name
        self.callback = callback
        self.model = None
        self.is_loaded = False
        self.is_loading = False
        self._listener = _VoskListener(self.callback)
        self._recognizer = None
        self._speech_service = None
        self._class_loader = None
        self._context = None
        self._cb_model = None
        self._cb_err = None
        base_dir = os.environ.get("ANDROID_PRIVATE") or os.getcwd()
        self._log_path = os.path.join(base_dir, "vosk_runtime.log")

    def _log(self, message):
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            line = f"[{ts}] {message}"
            print(line)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _get_context(self):
        if self._context is not None:
            return self._context
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        self._context = PythonActivity.mActivity
        try:
            self._class_loader = self._context.getClassLoader()
        except Exception:
            self._class_loader = None
        try:
            JavaSystem = autoclass("java.lang.System")
            JavaSystem.setProperty("jna.nosys", "true")
            try:
                native_dir = self._context.getApplicationInfo().nativeLibraryDir
                if native_dir:
                    JavaSystem.setProperty("jna.boot.library.path", native_dir)
                    JavaSystem.setProperty("jna.library.path", native_dir)
                    self._log(f"jna paths: {native_dir}")
            except Exception as e:
                self._log(f"jna path error: {e}")
        except Exception as e:
            self._log(f"jna property error: {e}")
        return self._context

    def _autoclass(self, name):
        if self._class_loader is not None:
            try:
                return autoclass(name, class_loader=self._class_loader)
            except TypeError:
                return autoclass(name)
            except Exception:
                return autoclass(name)
        return autoclass(name)

    def load_model(self):
        if platform != "android":
            self.callback("ERROR", "Android only")
            return
        if self.is_loaded or self.is_loading:
            return
        self.is_loading = True
        self._get_context()
        self._log(f"load_model start: asset={self.model_asset_name}")

        def _run_unpack():
            try:
                assets = self._context.getAssets()
                root_items = assets.list("")
                model_dir = self.model_asset_name
                model_items = assets.list(model_dir)
                self._log(f"assets root: {list(root_items) if root_items else 'None'}")
                self._log(f"assets model: {list(model_items) if model_items else 'None'}")
                if model_items is None or len(model_items) == 0:
                    if root_items is None or model_dir not in list(root_items):
                        self.is_loading = False
                        self.callback("VOSK_ERROR", f"Model assets not found: {model_dir}")
                        self._log(f"model assets not found: {model_dir}")
                        return
                StorageService = self._autoclass("org.vosk.android.StorageService")
                self._cb_model = _VoskStorageModelCallback(self)
                self._cb_err = _VoskStorageErrorCallback(self)
                StorageService.unpack(self._context, self.model_asset_name, self.model_asset_name, self._cb_model, self._cb_err)
            except Exception as e:
                self.is_loading = False
                self.callback("VOSK_ERROR", f"Load Failed: {e}")
                self._log(f"load failed: {e}")

        if "run_on_ui_thread" in globals():
            run_on_ui_thread(_run_unpack)()
        else:
            _run_unpack()

    def start_listening(self):
        if not self.is_loaded:
            self.callback("ERROR", "Model not loaded")
            return
        try:
            Recognizer = self._autoclass("org.vosk.Recognizer")
            SpeechService = self._autoclass("org.vosk.android.SpeechService")
            if not self._recognizer:
                self._recognizer = Recognizer(self.model, 16000.0)
            if not self._speech_service:
                self._speech_service = SpeechService(self._recognizer, 16000.0)
            self._speech_service.startListening(self._listener)
        except Exception as e:
            self.callback("ERROR", f"Start Failed: {e}")

    def stop_listening(self):
        try:
            if self._speech_service:
                self._speech_service.stop()
                self._speech_service.shutdown()
        except Exception:
            pass
        self._speech_service = None
