import json
import os
import threading
import queue
import time
import ctypes
from kivy.clock import Clock
from kivy.utils import platform

# Global Vosk imports (lazy loaded)
Model = None
KaldiRecognizer = None

class VoskManager:
    def __init__(self, model_path, callback):
        self.model_path = model_path
        self.callback = callback
        self.recognizer = None
        self.audio_thread = None
        self.running = False
        self.model = None
        self.is_loaded = False
        self._load_queue = queue.Queue()

    def load_model(self):
        """Asynchronously load the model."""
        if self.is_loaded:
            return
            
        def _load():
            global Model, KaldiRecognizer
            try:
                # Pre-load libatomic if needed
                if platform == 'android':
                    try:
                        from jnius import autoclass
                        import shutil

                        PythonActivity = autoclass('org.kivy.android.PythonActivity')
                        context = PythonActivity.mActivity
                        files_dir = context.getFilesDir().getAbsolutePath()
                        native_lib_dir = context.getApplicationInfo().nativeLibraryDir

                        src_atomic = os.path.join(native_lib_dir, "libatomic_custom.so")
                        dst_atomic_custom = os.path.join(files_dir, "libatomic_custom.so")
                        dst_atomic_soname = os.path.join(files_dir, "libatomic.so.1")
                        src_vosk = os.path.join(native_lib_dir, "libvosk.so")
                        dst_vosk = os.path.join(files_dir, "libvosk.so")

                        if os.path.exists(src_atomic):
                            try:
                                shutil.copy2(src_atomic, dst_atomic_custom)
                                shutil.copy2(src_atomic, dst_atomic_soname)
                            except Exception:
                                pass

                        if os.path.exists(src_vosk):
                            try:
                                shutil.copy2(src_vosk, dst_vosk)
                            except Exception:
                                pass

                        os.environ["LD_LIBRARY_PATH"] = f"{files_dir}:{native_lib_dir}"

                        flags = ctypes.RTLD_GLOBAL
                        try:
                            ctypes.CDLL(dst_atomic_soname, mode=flags)
                        except Exception:
                            try:
                                ctypes.CDLL(src_atomic, mode=flags)
                            except Exception:
                                pass

                        try:
                            ctypes.CDLL(dst_vosk, mode=flags)
                        except Exception:
                            try:
                                ctypes.CDLL(src_vosk, mode=flags)
                            except Exception:
                                pass

                    except Exception as e:
                        # Sometimes it might be in a different path or already loaded
                        pass

                if Model is None:
                    from vosk import Model, KaldiRecognizer, SetLogLevel
                    SetLogLevel(-1) # Quiet
                
                if not os.path.exists(self.model_path):
                    self.callback("ERROR", f"Model not found at {self.model_path}")
                    return

                self.model = Model(self.model_path)
                self.is_loaded = True
                self.callback("READY", "Model Loaded")
            except Exception as e:
                self.callback("ERROR", f"Load Failed: {e}")

        threading.Thread(target=_load, daemon=True).start()

    def start_listening(self):
        if not self.is_loaded:
            self.callback("ERROR", "Model not loaded")
            return
            
        if self.running:
            return

        self.running = True
        self.audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self.audio_thread.start()

    def stop_listening(self):
        self.running = False
        if self.audio_thread:
            self.audio_thread.join(timeout=1.0)
            self.audio_thread = None

    def _audio_loop(self):
        try:
            from jnius import autoclass
            
            # Android AudioRecord setup
            AudioRecord = autoclass('android.media.AudioRecord')
            MediaRecorder = autoclass('android.media.MediaRecorder')
            AudioFormat = autoclass('android.media.AudioFormat')
            
            Source = MediaRecorder.AudioSource.MIC
            Rate = 16000
            ChannelConfig = AudioFormat.CHANNEL_IN_MONO
            Format = AudioFormat.ENCODING_PCM_16BIT
            
            BufferSize = AudioRecord.getMinBufferSize(Rate, ChannelConfig, Format)
            if BufferSize <= 0:
                 BufferSize = 4096

            recorder = AudioRecord(Source, Rate, ChannelConfig, Format, BufferSize * 2)
            
            if recorder.getState() != AudioRecord.STATE_INITIALIZED:
                self.callback("ERROR", "AudioRecord init failed")
                self.running = False
                return

            recorder.startRecording()
            
            rec = KaldiRecognizer(self.model, Rate)
            
            # Buffer for reading
            buffer = bytearray(BufferSize)
            
            while self.running:
                # Read audio data
                read_size = recorder.read(buffer, 0, len(buffer))
                if read_size > 0:
                    data = bytes(buffer[:read_size])
                    if rec.AcceptWaveform(data):
                        res = json.loads(rec.Result())
                        text = res.get('text', '')
                        if text:
                            self.callback("RESULT", text)
                    else:
                        partial = json.loads(rec.PartialResult())
                        text = partial.get('partial', '')
                        if text:
                            self.callback("PARTIAL", text)
                else:
                    time.sleep(0.01)

            # Final result
            res = json.loads(rec.FinalResult())
            text = res.get('text', '')
            if text:
                self.callback("RESULT", text)

            recorder.stop()
            recorder.release()
            
        except Exception as e:
            self.callback("ERROR", f"Audio Error: {e}")
            self.running = False
