import logging
import threading
import os
import sys
import json
import time
import re
import traceback

if os.environ.get("ANDROID_PRIVATE"):
    os.environ.setdefault("KIVY_HOME", os.path.join(os.environ["ANDROID_PRIVATE"], ".kivy"))

os.environ.setdefault("FORCE_IPV4", "1")

try:
    from jnius import autoclass, java_method, PythonJavaClass

    System = autoclass("java.lang.System")
    System.setProperty("java.net.preferIPv4Stack", "true")
    
    Context = autoclass("android.content.Context")
    Intent = autoclass("android.content.Intent")
    Uri = autoclass("android.net.Uri")
    Settings = autoclass("android.provider.Settings")
    
    # Speech Recognition
    SpeechRecognizer = autoclass("android.speech.SpeechRecognizer")
    RecognizerIntent = autoclass("android.speech.RecognizerIntent")
    
    class RecognitionListener(PythonJavaClass):
        __javainterfaces__ = ["android/speech/RecognitionListener"]
        __javacontext__ = "app"

        def __init__(self, callback):
            super().__init__()
            self.callback = callback

        @java_method("()V")
        def onBeginningOfSpeech(self):
            print("Speech: Beginning of speech")

        @java_method("([B)V")
        def onBufferReceived(self, buffer):
            pass

        @java_method("()V")
        def onEndOfSpeech(self):
            print("Speech: End of speech")

        @java_method("(I)V")
        def onError(self, error):
            print(f"Speech: Error {error}")
            # Map error codes to messages if needed
            self.callback("ERROR", str(error))

        @java_method("(ILandroid/os/Bundle;)V")
        def onEvent(self, eventType, params):
            pass

        @java_method("(Landroid/os/Bundle;)V")
        def onPartialResults(self, partialResults):
            matches = partialResults.getStringArrayList(RecognizerIntent.EXTRA_RESULTS)
            if matches and matches.size() > 0:
                text = matches.get(0)
                self.callback("PARTIAL", text)

        @java_method("(Landroid/os/Bundle;)V")
        def onReadyForSpeech(self, params):
            print("Speech: Ready for speech")
            self.callback("READY", None)

        @java_method("(Landroid/os/Bundle;)V")
        def onResults(self, results):
            matches = results.getStringArrayList(RecognizerIntent.EXTRA_RESULTS)
            if matches and matches.size() > 0:
                text = matches.get(0)
                self.callback("RESULT", text)
            else:
                self.callback("RESULT", "")

        @java_method("(F)V")
        def onRmsChanged(self, rmsdB):
            pass

except Exception:
    class RecognitionListener: pass
    SpeechRecognizer = None
    RecognizerIntent = None
    pass

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.modalview import ModalView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.dropdown import DropDown
from kivy.graphics import Color, RoundedRectangle, Ellipse, Rectangle, Line
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import platform
from kivy.animation import Animation

if platform == "android":
    from android.permissions import request_permissions, check_permission, Permission
    from android.runnable import run_on_ui_thread
else:
    def run_on_ui_thread(f):
        return f

import order_backend
import stt_vosk_android as stt_vosk

def _get_android_external_files_dir():
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        d = activity.getExternalFilesDir(None)
        if d is not None:
            p = str(d.getAbsolutePath())
            if p:
                return p
    except Exception:
        return None
    return None

def _get_inbox_task_paths():
    paths = []
    base = _get_android_external_files_dir()
    if base:
        try:
            paths.append(os.path.join(base, "AppAgent", "inbox_task.json"))
        except Exception:
            pass
    paths.append("/sdcard/AppAgent/inbox_task.json")
    return [p for p in paths if p]

def _pick_cjk_font():
    candidates = [
        "/system/fonts/NotoSansCJK-Regular.ttc",
        "/system/fonts/NotoSansCJKsc-Regular.otf",
        "/system/fonts/NotoSansSC-Regular.otf",
        "/system/fonts/NotoSansHans-Regular.otf",
        "/system/fonts/NotoSerifCJK-Regular.ttc",
        "/system/fonts/DroidSansFallback.ttf",
        "/system/fonts/DroidSansFallbackFull.ttf",
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                return p
        except Exception:
            pass
    return None

def _normalize_speech_text(text):
    if not text:
        return text
    strong_replacements = [
        ("顿号", "、"),
        ("逗号", "，"),
        ("句号", "。"),
        ("问号", "？"),
        ("感叹号", "！"),
        ("冒号", "："),
        ("分号", "；"),
        ("省略号", "…"),
        ("破折号", "—"),
        ("斜杠", "/"),
        ("反斜杠", "\\"),
        ("左括号", "（"),
        ("右括号", "）"),
        ("括号", "（）"),
        ("双引号", "“”"),
        ("单引号", "‘’"),
    ]
    weak_replacements = [
        ("成都好", "，"),
        ("豆号", "，"),
        ("斗号", "，"),
        ("豆好", "，"),
        ("逗好", "，"),
        ("都好", "，"),
        ("多好", "，"),
    ]
    for word, sym in strong_replacements:
        pattern = rf"\s*{re.escape(word)}\s*"
        text = re.sub(pattern, lambda m, s=sym: s, text)
    cjk = r"\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef"
    for word, sym in weak_replacements:
        pattern = rf"(?<![{cjk}])\s*{re.escape(word)}\s*(?![{cjk}])"
        text = re.sub(pattern, lambda m, s=sym: s, text)
    return re.sub(rf"(?<=[{cjk}])\s+(?=[{cjk}])", "", text)

def request_ignore_battery_optimizations():
    try:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        
        power_manager = activity.getSystemService(Context.POWER_SERVICE)
        package_name = activity.getPackageName()
        
        if not power_manager.isIgnoringBatteryOptimizations(package_name):
            intent = Intent()
            intent.setAction(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.setData(Uri.parse("package:" + package_name))
            activity.startActivity(intent)
            return True
        else:
            return False
    except Exception as e:
        print(f"[Main] Failed to request ignore battery optimizations: {e}")
        return False

class ChatBubble(Label):
    def __init__(self, is_user=False, **kwargs):
        super().__init__(**kwargs)
        self.is_user = is_user
        self.color = (0, 0, 0, 1)
        self.padding = (dp(15), dp(10))
        self.halign = 'left'
        self.valign = 'middle'
        self.size_hint = (None, None)
        self.width = dp(240)
        self.bind(texture_size=self._update_size)
        self.bind(pos=self._update_size)

    def _update_size(self, *args):
        self.text_size = (self.width - dp(30), None)
        self.height = self.texture_size[1] + dp(20)
        self.canvas.before.clear()
        with self.canvas.before:
            if self.is_user:
                Color(1, 1, 1, 1) # User: White (Right)
            else:
                Color(0.9, 0.9, 0.9, 1) # AI: Light Gray (Left)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(15)])

class ChatListItem(BoxLayout):
    def __init__(self, text, is_user=False, font_name=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.padding = [dp(10), dp(5)]
        self.spacing = dp(10)
        
        # Avatar placeholder
        self.avatar = Label(size_hint=(None, None), size=(dp(40), dp(40)), text="S", color=(1,1,1,1), bold=True)
        with self.avatar.canvas.before:
            Color(0, 0, 0, 1) # Black background
            self.avatar_circle = Ellipse(pos=self.avatar.pos, size=self.avatar.size)
        self.avatar.bind(pos=self._update_avatar, size=self._update_avatar)

        self.bubble = ChatBubble(text=text, is_user=is_user, font_name=font_name)
        
        if is_user:
            self.add_widget(Widget()) # Spacer to push right
            self.add_widget(self.bubble)
        else:
            self.add_widget(self.avatar)
            self.add_widget(self.bubble)
            self.add_widget(Widget()) # Spacer to push left

        self.bubble.bind(height=self._update_height)
        Clock.schedule_once(lambda dt: self._update_height(), 0)

    def _update_avatar(self, instance, *args):
        self.avatar_circle.pos = instance.pos
        self.avatar_circle.size = instance.size

    def _update_height(self, *args):
        self.height = max(self.bubble.height, dp(40)) + dp(10)

from kivy.uix.widget import Widget
from math import cos, sin, pi

class IconWidget(Widget):
    def __init__(self, icon_type='circle', color=(0.2, 0.2, 0.2, 1), **kwargs):
        super().__init__(**kwargs)
        self.icon_type = icon_type
        self.icon_color = color
        self.bind(pos=self._update_canvas, size=self._update_canvas)

    def _update_canvas(self, *args):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        w, h = self.size
        dim = min(w, h)
        r = dim * 0.35 # Radius for circles
        
        with self.canvas:
            Color(*self.icon_color)
            if self.icon_type == 'history':
                # Clock
                Line(circle=(cx, cy, r), width=dp(1.2))
                Line(points=[cx, cy + r*0.6, cx, cy], width=dp(1.2)) # Hour hand (up)
                Line(points=[cx, cy, cx + r*0.5, cy - r*0.2], width=dp(1.2)) # Minute hand (slight angle)
            elif self.icon_type == 'search':
                # Magnifying glass
                Line(circle=(cx - r*0.2, cy + r*0.2, r*0.7), width=dp(1.2))
                Line(points=[cx + r*0.4, cy - r*0.4, cx + r*0.9, cy - r*0.9], width=dp(2))
            elif self.icon_type == 'stop':
                # Stop square
                RoundedRectangle(pos=(cx - r*0.7, cy - r*0.7), size=(r*1.4, r*1.4), radius=[dp(2)])
            elif self.icon_type == 'add_user':
                # User head + body
                Line(circle=(cx, cy + r*0.4, r*0.5), width=dp(1.2)) # Head
                Line(ellipse=(cx - r*0.8, cy - r*0.8, r*1.6, r*1.0), angle_start=0, angle_end=180, width=dp(1.2)) # Body arc
                # Plus sign (small)
                px, py = cx + r*0.6, cy + r*0.4
                Line(points=[px - r*0.3, py, px + r*0.3, py], width=dp(1.2))
                Line(points=[px, py - r*0.3, px, py + r*0.3], width=dp(1.2))
            elif self.icon_type == 'trash':
                # Trash can
                Line(rectangle=(cx - r*0.5, cy - r*0.7, r*1.0, r*1.2), width=dp(1.2)) # Bin
                Line(points=[cx - r*0.6, cy + r*0.5, cx + r*0.6, cy + r*0.5], width=dp(1.2)) # Lid
                Line(points=[cx, cy + r*0.5, cx, cy + r*0.7], width=dp(1.2)) # Handle
            elif self.icon_type == 'web':
                # Globe/Network
                Line(circle=(cx, cy, r), width=dp(1.2)) # Circle
                Line(points=[cx - r, cy, cx + r, cy], width=dp(1.2)) # Equator
                Line(points=[cx, cy - r, cx, cy + r], width=dp(1.2)) # Meridian
                # Ellipse for longitude
                Line(ellipse=(cx - r*0.5, cy - r, r, r*2), width=dp(1))
            elif self.icon_type == 'email':
                # Envelope
                w_r, h_r = r*1.4, r*1.0
                Line(rectangle=(cx - w_r/2, cy - h_r/2, w_r, h_r), width=dp(1.2))
                Line(points=[cx - w_r/2, cy + h_r/2, cx, cy, cx + w_r/2, cy + h_r/2], width=dp(1.2))
            elif self.icon_type == 'lock':
                # Padlock
                body_w, body_h = r*1.0, r*0.8
                shackle_r = r*0.35
                # Body
                Line(rectangle=(cx - body_w/2, cy - body_h/2, body_w, body_h), width=dp(1.2))
                # Shackle
                Line(ellipse=(cx - shackle_r, cy + body_h/2 - shackle_r, shackle_r*2, shackle_r*2), angle_start=0, angle_end=180, width=dp(1.2))
                # Keyhole
                Line(circle=(cx, cy, r*0.1), width=dp(1.2))
                Line(points=[cx, cy, cx, cy - r*0.2], width=dp(1.2))
            elif self.icon_type == 'eye':
                # Eye
                Line(ellipse=(cx - r, cy - r*0.6, r*2, r*1.2), width=dp(1.2))
                Line(circle=(cx, cy, r*0.3), width=dp(1.2))
            elif self.icon_type == 'user_large':
                # Large User Avatar (Filled)
                Color(0.5, 0.5, 0.5, 1) # Darker Gray
                # Head
                head_r = r * 0.5
                Ellipse(pos=(cx - head_r, cy + r*0.1), size=(head_r*2, head_r*2))
                # Shoulders (Masked by circle usually, but here just an arc)
                body_w, body_h = r*1.6, r*1.2
                # Start angle 0 is right, 180 is left. 
                # We want a semi-circle pointing up.
                Ellipse(pos=(cx - body_w/2, cy - r*0.9), size=(body_w, body_h), angle_start=0, angle_end=180)

class MenuButton(Button):
    def __init__(self, icon_type, label_text, font_name=None, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_disabled_normal = ''
        self.background_disabled_down = ''
        self.background_color = (0, 0, 0, 0)
        self.size_hint_y = None
        self.height = dp(50)
        self.icon_type = icon_type
        self.label_text = label_text
        
        # Layout for content
        self.layout = BoxLayout(orientation='horizontal', padding=[dp(20), 0], spacing=dp(15))
        self.layout.size = self.size
        self.layout.pos = self.pos
        
        # Icon Background + Canvas Icon
        self.icon_box = BoxLayout(size_hint=(None, None), size=(dp(36), dp(36)))
        with self.icon_box.canvas.before:
            Color(0.95, 0.95, 0.95, 1) # Light gray circle background
            self.icon_bg = Ellipse(pos=self.icon_box.pos, size=self.icon_box.size)
        self.icon_box.bind(pos=self._update_icon_bg, size=self._update_icon_bg)

        # Create Custom Icon Widget
        self.icon_widget = IconWidget(icon_type=icon_type, size_hint=(1, 1))
        self.icon_box.add_widget(self.icon_widget)

        self.text_label = Label(text=label_text, size_hint=(1, 1), 
                                font_size=dp(16), color=(0.2, 0.2, 0.2, 1), 
                                halign='left', valign='middle')
        self.text_label.bind(size=self.text_label.setter('text_size'))
        
        if font_name:
            self.text_label.font_name = font_name
        
        self.layout.add_widget(self.icon_box)
        self.layout.add_widget(self.text_label)
        self.add_widget(self.layout)
        
        self.bind(pos=self._update_layout, size=self._update_layout)

    def _update_layout(self, *args):
        self.layout.pos = (self.x, self.y + (self.height - self.layout.height)/2) # Center vertically
        self.layout.size = self.size

    def _update_icon_bg(self, instance, value):
        self.icon_bg.pos = instance.pos
        self.icon_bg.size = instance.size

class SideBar(BoxLayout):
    def __init__(self, app_instance, **kwargs):
        super().__init__(**kwargs)
        self.app = app_instance
        self.orientation = 'vertical'
        self.size_hint = (None, 1)
        self.width = dp(280)
        self.x = -self.width # Initially hidden
        
        # Background
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self.bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[0, dp(20), dp(20), 0])
        self.bind(pos=self._update_bg, size=self._update_bg)

        # Header (User Info)
        header = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(150), padding=dp(20), spacing=dp(10))
        
        # Avatar
        self.avatar = Label(size_hint=(None, None), size=(dp(60), dp(60)), text="")
        with self.avatar.canvas.before:
            Color(0.8, 0.8, 0.8, 1)
            self.avatar_bg = Ellipse(pos=self.avatar.pos, size=self.avatar.size)
        self.avatar.bind(pos=self._update_avatar_bg, size=self._update_avatar_bg)
        
        # Username
        username = Label(text="Tasks", font_size=dp(20), bold=True, 
                         color=(0, 0, 0, 1), size_hint_y=None, height=dp(30),
                         halign='left', valign='middle')
        username.bind(size=username.setter('text_size'))
        
        header.add_widget(self.avatar)
        header.add_widget(username)
        self.add_widget(header)
        
        # Menu Items ScrollView
        scroll = ScrollView(size_hint=(1, 1))
        menu_list = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        menu_list.bind(minimum_height=menu_list.setter('height'))
        
        font_name = self.app._cjk_font if hasattr(self.app, '_cjk_font') else None

        # History
        btn_history = MenuButton("history", "History", font_name=font_name)
        menu_list.add_widget(btn_history)

        # Run Task
        self.btn_start = MenuButton("search", "Run Task", font_name=font_name)
        self.btn_start.bind(on_release=lambda x: self.on_menu_select(self.app.start_query))
        menu_list.add_widget(self.btn_start)

        # Stop Task
        self.btn_stop = MenuButton("stop", "Stop Task", font_name=font_name)
        self.btn_stop.bind(on_release=lambda x: self.on_menu_select(self.app.stop_query))
        self.btn_stop.disabled = True
        self.btn_stop.opacity = 0.5
        menu_list.add_widget(self.btn_stop)
        
        # Clear Log
        btn_clear = MenuButton("trash", "Clear Log", font_name=font_name)
        btn_clear.bind(on_release=lambda x: self.on_menu_select(self.app.clear_log))
        menu_list.add_widget(btn_clear)
            
        scroll.add_widget(menu_list)
        self.add_widget(scroll)

    def _update_bg(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

    def _update_avatar_bg(self, instance, *args):
        self.avatar_bg.pos = instance.pos
        self.avatar_bg.size = instance.size

    def on_menu_select(self, action):
        self.app.toggle_sidebar()
        if action:
            # Delay slightly for animation
            Clock.schedule_once(lambda dt: action(None), 0.3)

class RoundedInputWrapper(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.padding = [dp(10), dp(5)]
        self.spacing = dp(5)
        # Background: White Rounded Rectangle
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self.bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(20)])
        self.bind(pos=self._update_bg, size=self._update_bg)

    def _update_bg(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

class OrderQueryApp(App):
    def build(self):
        self.backend = order_backend.OrderBackend(log_callback=self.update_log, base_log_dir=self.user_data_dir)
        self.bg_service = None
        self._android_service = None
        self._speech_recognizer = None
        self._speech_intent = None
        self._activity = None
        self._vosk_manager = None
        self._using_vosk = False
        
        if platform == "android":
            request_permissions([Permission.RECORD_AUDIO])
            try:
                from jnius import autoclass
                JavaSystem = autoclass("java.lang.System")
                JavaSystem.setProperty("jna.nosys", "true")
            except Exception:
                pass
            
            # Init Vosk
            model_asset_name = "model"
            self._vosk_manager = stt_vosk.VoskManager(model_asset_name, self._on_speech_result)
            self._vosk_manager.load_model()
            
        if os.environ.get("ANDROID_PRIVATE"):
            try:
                from android import AndroidService, activity as android_activity
                self._android_service = AndroidService("Order Query", "Running in background...")
                # Bind activity result for fallback intent
                android_activity.bind(on_activity_result=self.on_activity_result)
                android_activity.bind(on_new_intent=self._on_new_intent)
            except Exception:
                self._android_service = None
                
            try:
                # Initialize Speech Recognizer
                self.create_speech_recognizer()
            except Exception as e:
                print(f"Speech Recognizer Init Failed: {e}")
                self._speech_recognizer = None

        self._android_service_started = False
        self._service_log_path = None
        self._service_log_pos = 0
        self._service_log_event = None
        self._service_start_check_event = None
        self._service_log_baseline_size = 0
        self._pending_move_home_after_permission = False
        self._pending_notification_permission = False
        self._pending_battery_permission = False
        self._pending_adb_authorization = False
        self._pending_adb_since = 0.0
        self._adb_status_last = None
        self._permission_watch_event = None
        self._capture_ready_path = None
        self._capture_ready_armed = False
        self._inbox_task_paths = None
        self._inbox_task_event = None
        if os.environ.get("ANDROID_PRIVATE"):
            try:
                self._service_log_path = os.path.join(os.environ["ANDROID_PRIVATE"], "service_runtime.log")
            except Exception:
                self._service_log_path = None
            try:
                self._capture_ready_path = os.path.join(os.environ["ANDROID_PRIVATE"], "capture_ready.flag")
            except Exception:
                self._capture_ready_path = None

        if platform == "android":
            try:
                self._inbox_task_paths = _get_inbox_task_paths()
            except Exception:
                self._inbox_task_paths = None
            if self._inbox_task_paths:
                try:
                    for p in list(self._inbox_task_paths):
                        inbox_dir = os.path.dirname(p)
                        if inbox_dir:
                            os.makedirs(inbox_dir, exist_ok=True)
                except Exception:
                    pass
                try:
                    self._inbox_task_event = Clock.schedule_interval(self._poll_inbox_task, 1.0)
                except Exception:
                    self._inbox_task_event = None
        self._move_home_event = None
        self._last_move_home_at = 0.0
        self._last_start_query_at = 0.0
        self._manual_task_thread = None
        self._manual_task_running = False
        self._cjk_font = _pick_cjk_font() if os.environ.get("ANDROID_PRIVATE") else None
        
        # Root Layout
        # Root Layout (FloatLayout to allow overlays)
        self.root_layout = FloatLayout()
        
        # Main Content Layout (BoxLayout)
        self.main_content = BoxLayout(orientation='vertical')
        with self.main_content.canvas.before:
            Color(0.96, 0.96, 0.96, 1) # App Background
            self.root_bg = Rectangle(pos=self.main_content.pos, size=self.main_content.size)
        self.main_content.bind(pos=self._update_root_bg, size=self._update_root_bg)
        
        self.root_layout.add_widget(self.main_content)

        # Top Bar
        top_bar = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), padding=[dp(10), 0])
        with top_bar.canvas.before:
            Color(1, 1, 1, 1)
            self.top_bar_bg = Rectangle(pos=top_bar.pos, size=top_bar.size)
        top_bar.bind(pos=self._update_top_bar_bg, size=self._update_top_bar_bg)

        # Menu Button
        btn_menu = Button(text="=", size_hint=(None, None), size=(dp(40), dp(40)), 
                          background_color=(0,0,0,0), color=(0,0,0,1), font_size=dp(30))
        btn_menu.bind(on_release=self.toggle_sidebar)
        top_bar.add_widget(btn_menu)
        
        # Title
        title = Label(text="Sito AI", color=(0,0,0,1), font_size=dp(18), bold=True)
        if self._cjk_font: title.font_name = self._cjk_font
        top_bar.add_widget(title)
        
        # Right spacer
        top_bar.add_widget(Label(size_hint_x=None, width=dp(40)))
        
        self.main_content.add_widget(top_bar)
        
        # Chat Area
        self.scroll_view = ScrollView()
        
        # Wrapper to handle alignment (Top-Align content)
        self.chat_wrapper = FloatLayout(size_hint_y=None)
        
        self.chat_list = GridLayout(cols=1, size_hint_y=None, spacing=dp(10), padding=dp(10))
        self.chat_list.bind(minimum_height=self.chat_list.setter('height'))
        
        # Position chat_list at the top of the wrapper
        self.chat_list.pos_hint = {'top': 1, 'x': 0}
        
        self.chat_wrapper.add_widget(self.chat_list)
        self.scroll_view.add_widget(self.chat_wrapper)
        
        # Bind wrapper height to be at least ScrollView height, but expand with content
        def update_wrapper_height(*args):
            self.chat_wrapper.height = max(self.chat_list.height, self.scroll_view.height)
            
        self.chat_list.bind(height=update_wrapper_height)
        self.scroll_view.bind(height=update_wrapper_height)
        
        self.main_content.add_widget(self.scroll_view)
        
        # Input Area
        input_area = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(60), padding=[dp(10), dp(10)], spacing=dp(10))
        with input_area.canvas.before:
            Color(0.96, 0.96, 0.96, 1) # Match root background
            self.input_area_bg = Rectangle(pos=input_area.pos, size=input_area.size)
        input_area.bind(pos=self._update_input_area_bg, size=self._update_input_area_bg)
        
        # Rounded Container for Input + Voice Button
        self.input_wrapper = RoundedInputWrapper(size_hint_x=1)
        
        # Text Input (Transparent)
        self.msg_input = TextInput(
            hint_text="Text message", 
            multiline=False, 
            background_normal='', 
            background_active='',
            background_disabled_normal='',
            background_color=(0,0,0,0),
            foreground_color=(0,0,0,1),
            cursor_color=(0,0,0,1),
            padding=[dp(5), dp(10)],
            font_size=dp(16),
            size_hint=(1, None),
            height=dp(40),
            pos_hint={'center_y': 0.5}
        )
        if self._cjk_font: self.msg_input.font_name = self._cjk_font
        self.msg_input.bind(text=self.on_text_change)
        
        # Voice Toggle Button (Inside wrapper, right side)
        # Using simple 'M' for Mic and 'K' for Keyboard to ensure rendering if unicode fails
        self.btn_voice_toggle = Button(
            text="Mic", 
            size_hint=(None, None), 
            size=(dp(40), dp(40)), 
            background_normal='', 
            background_color=(0,0,0,0), 
            color=(0.5, 0.5, 0.5, 1),
            font_size=dp(14),
            pos_hint={'center_y': 0.5}
        )
        self.btn_voice_toggle.bind(on_release=self.toggle_voice_input)
        
        # Add components to wrapper
        self.input_wrapper.add_widget(self.msg_input)
        self.input_wrapper.add_widget(self.btn_voice_toggle)

        # Voice Record Button (Hidden initially, replaces text input)
        self.btn_voice_record = Button(
            text="按住说话", 
            size_hint=(1, None),
            height=dp(36),
            pos_hint={'center_y': 0.5},
            background_normal='', 
            background_color=(0.9, 0.9, 0.9, 1), 
            color=(0, 0, 0, 1)
        )
        if self._cjk_font:
            self.btn_voice_record.font_name = self._cjk_font
        self.btn_voice_record.bind(on_press=self.on_voice_record_press, on_release=self.on_voice_record_release)
        # Add rounded bg for voice button
        with self.btn_voice_record.canvas.before:
            Color(0.9, 0.9, 0.9, 1)
            self.btn_voice_record_bg = RoundedRectangle(pos=self.btn_voice_record.pos, size=self.btn_voice_record.size, radius=[dp(10)])
        self.btn_voice_record.bind(pos=self._update_voice_record_bg, size=self._update_voice_record_bg)

        self.is_voice_mode = False
        self._is_recording = False

        # Send Button (Outside wrapper, right side)
        # Using '>' as safe fallback
        self.btn_send = Button(
            text=">", 
            size_hint=(None, None), 
            size=(dp(40), dp(40)), 
            background_normal='', 
            background_color=(0,0,0,0),
            font_size=dp(18)
        )
        # Make send button circular
        with self.btn_send.canvas.before:
            self.btn_send_color = Color(0.8, 0.8, 0.8, 1) # Gray default
            self.btn_send_bg = Ellipse(pos=self.btn_send.pos, size=self.btn_send.size)
        self.btn_send.bind(pos=self._update_send_btn_bg, size=self._update_send_btn_bg)
        self.btn_send.bind(on_release=self.send_message)
        
        input_area.add_widget(self.input_wrapper)
        input_area.add_widget(self.btn_send)
        
        self.main_content.add_widget(input_area)

        # Sidebar Scrim (Transparent button to close sidebar)
        self.sidebar_scrim = Button(
            background_color=(0,0,0,0),
            background_normal='',
            background_down='',
            background_disabled_normal='',
            background_disabled_down='',
            size_hint=(None, None),
            size=(0, 0),
            pos=(-2000, -2000)
        )
        self.sidebar_scrim.bind(on_release=self.close_sidebar)
        self.root_layout.add_widget(self.sidebar_scrim)
        
        # Sidebar
        self.sidebar = SideBar(self, pos_hint={})
        self.sidebar.x = -self.sidebar.width # Ensure initial position is off-screen
        self.root_layout.add_widget(self.sidebar)
        
        # Link buttons for backward compatibility with start_query/stop_query
        self.btn_start = self.sidebar.btn_start
        self.btn_stop = self.sidebar.btn_stop

        try:
            Window.bind(on_request_close=self._on_request_close)
        except Exception:
            pass

        if platform == "android":
            try:
                Clock.schedule_once(lambda dt: self._consume_initial_intent_task(), 0.5)
            except Exception:
                pass
        
        return self.root_layout

    def _update_root_bg(self, instance, value):
        self.root_bg.pos = instance.pos
        self.root_bg.size = instance.size

    def _update_top_bar_bg(self, instance, value):
        self.top_bar_bg.pos = instance.pos
        self.top_bar_bg.size = instance.size

    def _update_input_area_bg(self, instance, value):
        self.input_area_bg.pos = instance.pos
        self.input_area_bg.size = instance.size

    def _update_voice_toggle_bg(self, instance, value):
        pass # No longer needs separate background update as it's transparent now

    def _update_voice_record_bg(self, instance, value):
        self.btn_voice_record_bg.pos = instance.pos
        self.btn_voice_record_bg.size = instance.size

    def _update_send_btn_bg(self, instance, value):
        self.btn_send_bg.pos = instance.pos
        self.btn_send_bg.size = instance.size

    @run_on_ui_thread
    def create_speech_recognizer(self):
        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            self._activity = PythonActivity.mActivity
            
            # Destroy existing one if any
            if self._speech_recognizer:
                try:
                    self._speech_recognizer.destroy()
                except Exception:
                    pass
                self._speech_recognizer = None
            
            # Use Activity context, which is often safer for SpeechRecognizer
            self._speech_recognizer = SpeechRecognizer.createSpeechRecognizer(self._activity)
            self._speech_listener = RecognitionListener(self._on_speech_result)
            self._speech_recognizer.setRecognitionListener(self._speech_listener)
            
            self._speech_intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            self._speech_intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            self._speech_intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            self._speech_intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, True)
            self._speech_intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
            
            # Add CALLING_PACKAGE for Android 11+ visibility
            self._speech_intent.putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, self._activity.getPackageName())
        except Exception as e:
            print(f"Speech Recognizer Init Failed: {e}")
            self._speech_recognizer = None

    @run_on_ui_thread
    def start_listening(self):
        if not check_permission(Permission.RECORD_AUDIO):
            print("Speech: RECORD_AUDIO permission missing")
            request_permissions([Permission.RECORD_AUDIO])
            # Don't return, let user try again or fail gracefully
            return

        # Ensure recognizer exists
        if not self._speech_recognizer:
             # Check if recognition is available
             if not SpeechRecognizer.isRecognitionAvailable(self._activity):
                 print("Speech: Recognition NOT available on this device")
                 self.btn_voice_record.text = "No Service"
                 # Fallback to Intent (System Dialog)
                 try:
                     self._activity.startActivityForResult(self._speech_intent, 100)
                 except Exception as e:
                     print(f"Fallback Intent Failed: {e}")
                 return

             self.create_speech_recognizer()
             # Give it a moment to init before starting
             Clock.schedule_once(lambda dt: self.start_listening_internal(), 0.2)
        else:
             self.start_listening_internal()

    @run_on_ui_thread
    def start_listening_internal(self):
        if self._speech_recognizer:
            try:
                # Cancel previous listening to be safe
                self._speech_recognizer.cancel()
                self._speech_recognizer.startListening(self._speech_intent)
            except Exception as e:
                print(f"Start Listening Exception: {e}")
                # Try recreating if it fails hard
                self.create_speech_recognizer()

    @run_on_ui_thread
    def stop_listening(self):
        if self._speech_recognizer:
            try:
                self._speech_recognizer.stopListening()
            except Exception:
                pass
    
    # Handle Activity Result for Fallback Intent
    def on_activity_result(self, requestCode, resultCode, intent):
        if requestCode == 100 and resultCode == -1 and intent: # RESULT_OK = -1
            matches = intent.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            if matches and matches.size() > 0:
                text = matches.get(0)
                Clock.schedule_once(lambda dt: self._handle_speech_text(text), 0)

    def _extract_task_from_intent(self, intent):
        if not intent:
            return ""
        try:
            t = intent.getStringExtra("appagent_task")
            if t:
                return str(t).strip()
        except Exception:
            return ""
        return ""

    def _on_new_intent(self, intent):
        try:
            t = self._extract_task_from_intent(intent)
            if not t:
                return
            try:
                intent.removeExtra("appagent_task")
            except Exception:
                pass
            Clock.schedule_once(lambda dt: self._run_inbox_task(t), 0)
        except Exception:
            return

    def _consume_initial_intent_task(self):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if not activity:
                return
            intent = activity.getIntent()
            t = self._extract_task_from_intent(intent)
            if not t:
                return
            try:
                intent.removeExtra("appagent_task")
            except Exception:
                pass
            self._run_inbox_task(t)
        except Exception:
            return

    def on_voice_record_press(self, instance):
        if platform == "android":
             if self._is_recording:
                 return
             self._is_recording = True
             self.btn_voice_record.text = "录音中"
             # 1. Permission check
             if not check_permission(Permission.RECORD_AUDIO):
                 self.btn_voice_record.text = "Need Permission"
                 request_permissions([Permission.RECORD_AUDIO])
                 self._is_recording = False
                 return

             # 2. Try Vosk (Offline) First
             if self._vosk_manager:
                 if not self._vosk_manager.is_loaded:
                     self.btn_voice_record.text = "加载中..."
                     self._vosk_manager.load_model()
                     self._is_recording = False
                     return
                 self._using_vosk = True
                 self._vosk_manager.start_listening()
                 return

             # 3. Fallback to System SpeechRecognizer
             if not self._speech_recognizer:
                 try:
                     if SpeechRecognizer.isRecognitionAvailable(self._activity):
                        self.create_speech_recognizer()
                 except Exception:
                     pass

             if self._speech_recognizer:
                 self.start_listening()
                 return
             
             # 4. Fallback to Intent based system dialog
             self._start_voice_intent_fallback()
             self._is_recording = False
        else:
             # Fallback to mock if no recognizer (e.g. on PC)
             mock_text = "帮我下载小红书上的图片"
             self._handle_speech_text(mock_text)
             self._is_recording = False

    def on_voice_record_release(self, instance):
        if not self._is_recording:
            return
        self._is_recording = False
        if self._vosk_manager and self._vosk_manager.is_loaded:
            self._vosk_manager.stop_listening()
        elif self._speech_recognizer:
            self.stop_listening()
        self.btn_voice_record.text = "按住说话"

        self.btn_voice_record.background_color = (0.9, 0.9, 0.9, 1) # Reset color
        # Only reset text if it wasn't set to Error/No App Found/Opening...
        if self.btn_voice_record.text in ["Error", "No App Found", "Opening...", "Need Permission"]:
            pass # Keep it, let async reset it or user see it
        else:
             # Reset text logic
             self.btn_voice_record.text = "按住说话"

    def _start_voice_intent_fallback(self):
         try:
             intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
             intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
             intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
             intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "请说话...")
             
             # Verify if there is an activity to handle this intent
             packageManager = self._activity.getPackageManager()
             if intent.resolveActivity(packageManager):
                 self._activity.startActivityForResult(intent, 100)
             else:
                 # Even if resolveActivity fails, sometimes startActivity works or we can try a different intent
                 # But if it really fails, show toast
                 print("No Activity found to handle Speech Intent")
                 self.btn_voice_record.text = "No App Found"
                 
                 # Fallback to mock text so user isn't stuck (remove in production)
                 Clock.schedule_once(lambda dt: self._handle_speech_text("没有找到语音应用"), 1)
                 
         except Exception as e:
             print(f"Fallback Intent Failed: {e}")
             self.btn_voice_record.text = "Error"

    def _on_speech_result(self, event_type, data):
        if not hasattr(self, "btn_voice_record"):
            return
        if event_type == "VOSK_READY":
            self.btn_voice_record.text = "按住说话"
            return
        if event_type == "VOSK_ERROR":
            self.btn_voice_record.text = f"Error: {data}"
            return
        if event_type == "RESULT":
            self._using_vosk = False
            normalized = _normalize_speech_text(data)
            self._is_recording = False
            if normalized:
                self.btn_voice_record.text = "处理中..."
                Clock.schedule_once(lambda dt: self._handle_speech_text(normalized), 0)
            else:
                self.btn_voice_record.text = "按住说话"
        elif event_type == "PARTIAL":
            return
        elif event_type == "READY":
            Clock.schedule_once(lambda dt: setattr(self.btn_voice_record, 'text', "录音中"), 0)
        elif event_type == "ERROR":
            err_msg = f"Err: {data}"
            print(f"Speech Error: {data}")

            if self._using_vosk:
                self._using_vosk = False
                self._is_recording = False
                Clock.schedule_once(lambda dt: setattr(self.btn_voice_record, 'text', err_msg), 0)
                return
            
            # Special handling for Client Error (5) or Busy (8) or No Match (7)
            # 5: ERROR_CLIENT - Other client side errors
            # 8: ERROR_RECOGNIZER_BUSY
            # 7: ERROR_NO_MATCH
            err_code = str(data)
            if err_code in ["5", "8"]: 
                 # Critical error, fallback to Intent immediately
                 err_msg = "Switching..."
                 Clock.schedule_once(lambda dt: self._start_voice_intent_fallback(), 0.5)
                 # Force destroy current recognizer as it might be buggy
                 self._speech_recognizer = None
            elif err_code == "7":
                 err_msg = "No Match"

            # Reset UI if error occurs early
            self._is_recording = False
            Clock.schedule_once(lambda dt: setattr(self.btn_voice_record, 'text', err_msg), 0)

    def _handle_speech_text(self, text):
        if not text:
            return
        text = _normalize_speech_text(text)
            
        # Stop Vosk if running
        if self._vosk_manager:
             self._vosk_manager.stop_listening()
             
        # 1. Switch back to text mode first
        self.toggle_voice_input(None) 
        
        # 2. Schedule text update on next frame to ensure UI is ready
        def update_text(dt):
            self.msg_input.text = text
            self.on_text_change(self.msg_input, text)
            # 3. Set cursor to end
            self.msg_input.cursor = (len(text), 0)
            self.msg_input.focus = True
            if hasattr(self, "btn_voice_record"):
                self.btn_voice_record.text = "按住说话"
            
        Clock.schedule_once(update_text, 0.1)

    def toggle_voice_input(self, instance):
        self.input_wrapper.clear_widgets()
        if self.is_voice_mode:
            # Switch back to Text
            self.input_wrapper.add_widget(self.msg_input)
            self.btn_voice_toggle.text = "Mic"
            self.input_wrapper.add_widget(self.btn_voice_toggle)
            self.is_voice_mode = False
            self.on_text_change(self.msg_input, self.msg_input.text)
        else:
            # Switch to Voice
            self.input_wrapper.add_widget(self.btn_voice_record)
            self.btn_voice_toggle.text = "Key"
            self.input_wrapper.add_widget(self.btn_voice_toggle)
            self.is_voice_mode = True
            # In voice mode, send button is active (blue)
            self.btn_send_color.rgba = (0.2, 0.6, 1, 1)

    def on_text_change(self, instance, value):
        if value.strip():
            self.btn_send_color.rgba = (0.2, 0.6, 1, 1) # Blue
        else:
            self.btn_send_color.rgba = (0.8, 0.8, 0.8, 1) # Gray

    def show_menu(self, instance):
        self.menu.open(instance)

    def send_message(self, instance):
        if self.is_voice_mode:
            # Voice mode: simulate sending voice message (currently just logs)
            item = ChatListItem(text="[Voice Message]", is_user=True, font_name=self._cjk_font)
            self.chat_list.add_widget(item)
            Clock.schedule_once(lambda dt: setattr(self.scroll_view, 'scroll_y', 0), 0.1)
            # Reset to text mode after sending? Or stay? Let's stay in voice mode.
            return

        text = self.msg_input.text.strip()
        if not text:
            return
        self.msg_input.text = ""
        item = ChatListItem(text=text, is_user=True, font_name=self._cjk_font)
        self.chat_list.add_widget(item)
        Clock.schedule_once(lambda dt: setattr(self.scroll_view, 'scroll_y', 0), 0.1)
        self.start_query(None, task_text=text)

    def toggle_sidebar(self, instance=None):
        if self.sidebar.x < 0:
            # Open
            self.sidebar_scrim.size_hint = (1, 1)
            self.sidebar_scrim.pos = (0, 0)
            anim = Animation(x=0, d=0.3, t='out_cubic')
            anim.start(self.sidebar)
        else:
            # Close
            self.close_sidebar()

    def close_sidebar(self, instance=None):
        anim = Animation(x=-self.sidebar.width, d=0.3, t='out_cubic')
        def on_complete(*args):
            self.sidebar_scrim.size_hint = (None, None)
            self.sidebar_scrim.size = (0, 0)
            self.sidebar_scrim.pos = (-2000, -2000)
        anim.bind(on_complete=on_complete)
        anim.start(self.sidebar)

    def _on_request_close(self, *args):
        try:
            self.stop_query(None)
        except Exception:
            pass
        return False

    def on_pause(self):
        try:
            if os.environ.get("ANDROID_PRIVATE") and self._capture_ready_armed:
                self._capture_ready_armed = False
                p = self._capture_ready_path
                if p:
                    with open(p, "w", encoding="utf-8", errors="ignore") as f:
                        f.write(str(time.time() + 1.0))
        except Exception:
            pass
        return True

    def on_resume(self):
        try:
            if os.environ.get("ANDROID_PRIVATE") and self._pending_move_home_after_permission:
                self._pending_move_home_after_permission = False
                try:
                    if self._move_home_event is not None:
                        self._move_home_event.cancel()
                except Exception:
                    pass
                self._move_home_event = Clock.schedule_once(self._force_move_to_home_background, 0.6)
            if os.environ.get("ANDROID_PRIVATE") and (self._pending_notification_permission or self._pending_battery_permission):
                self._start_permission_watcher()
        except Exception:
            pass
        return

    def _schedule_move_home_after_permission(self):
        if not os.environ.get("ANDROID_PRIVATE"):
            return
        self._pending_move_home_after_permission = True

    def _force_move_to_home_background(self, dt=0):
        try:
            self._last_move_home_at = 0.0
        except Exception:
            pass
        self._move_to_home_background(dt)

    def _start_permission_watcher(self):
        if self._permission_watch_event is not None:
            return
        try:
            self._permission_watch_event = Clock.schedule_interval(self._permission_watch_tick, 0.6)
        except Exception:
            self._permission_watch_event = None

    def _stop_permission_watcher(self):
        try:
            if self._permission_watch_event is not None:
                self._permission_watch_event.cancel()
        except Exception:
            pass
        self._permission_watch_event = None

    def _permission_watch_tick(self, dt=0):
        if not os.environ.get("ANDROID_PRIVATE"):
            self._stop_permission_watcher()
            return
        try:
            if self._pending_adb_authorization:
                status = None
                try:
                    from scripts.and_controller import get_adb_status
                    status = str(get_adb_status() or "")
                except Exception:
                    try:
                        from and_controller import get_adb_status
                        status = str(get_adb_status() or "")
                    except Exception:
                        status = ""

                if status and status != self._adb_status_last:
                    self._adb_status_last = status
                    if status == "unreachable":
                        self.update_log("ADB未就绪：请开启无线调试，或用电脑执行 adb tcpip 5555。")
                    elif status == "unauthorized":
                        self.update_log("请在USB调试授权弹窗点击允许，完成后将自动返回桌面。")
                    elif status == "ready":
                        self.update_log("ADB已就绪。")

                if status in ("unauthorized", "unreachable") or (status or "").startswith("error"):
                    if (time.monotonic() - float(self._pending_adb_since or 0.0)) > 120.0:
                        self._pending_adb_authorization = False
                else:
                    self._pending_adb_authorization = False

            if self._pending_notification_permission:
                ok = True
                try:
                    from jnius import autoclass
                    Build_VERSION = autoclass("android.os.Build$VERSION")
                    sdk_int = int(getattr(Build_VERSION, "SDK_INT", 0) or 0)
                    if sdk_int >= 33:
                        from android.permissions import Permission, check_permission
                        ok = bool(check_permission(Permission.POST_NOTIFICATIONS))
                except Exception:
                    ok = False
                if ok:
                    self._pending_notification_permission = False

            if self._pending_battery_permission:
                ok = False
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    activity = PythonActivity.mActivity
                    Context = autoclass("android.content.Context")
                    power_manager = activity.getSystemService(Context.POWER_SERVICE)
                    package_name = activity.getPackageName()
                    ok = bool(power_manager.isIgnoringBatteryOptimizations(package_name))
                except Exception:
                    ok = False
                if ok:
                    self._pending_battery_permission = False

            if (not self._pending_notification_permission) and (not self._pending_battery_permission) and (not self._pending_adb_authorization):
                self._stop_permission_watcher()
                self._capture_ready_armed = True
                Clock.schedule_once(self._force_move_to_home_background, 0.6)
        except Exception:
            pass

    def _start_android_service(self):
        if not os.environ.get("ANDROID_PRIVATE"):
            return False
        if self._android_service_started:
            return True
        try:
            if self._android_service is not None:
                self._android_service.start("")
                self._android_service_started = True
                return True
        except Exception:
            pass

        try:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            pkg = str(activity.getPackageName())
            ServiceClass = autoclass(f"{pkg}.ServiceOrderqueryservice")
            Intent = autoclass("android.content.Intent")
            Build_VERSION = autoclass("android.os.Build$VERSION")

            intent = Intent(activity, ServiceClass)
            sdk_int = int(getattr(Build_VERSION, "SDK_INT", 0) or 0)
            if sdk_int >= 26:
                activity.startForegroundService(intent)
            else:
                activity.startService(intent)
            self._android_service_started = True
            return True
        except Exception:
            return False

    def _stop_android_service(self):
        if not os.environ.get("ANDROID_PRIVATE"):
            return
        try:
            if self._android_service is not None:
                self._android_service.stop()
        except Exception:
            pass
        try:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            pkg = str(activity.getPackageName())
            ServiceClass = autoclass(f"{pkg}.ServiceOrderqueryservice")
            Intent = autoclass("android.content.Intent")
            intent = Intent(activity, ServiceClass)
            activity.stopService(intent)
        except Exception:
            pass
        self._android_service_started = False

    def _poll_service_log(self, dt=0):
        p = self._service_log_path
        if not p:
            return
        try:
            if not os.path.exists(p):
                return
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                try:
                    f.seek(self._service_log_pos)
                except Exception:
                    self._service_log_pos = 0
                chunk = f.read()
                self._service_log_pos = f.tell()
            if chunk:
                for line in chunk.splitlines():
                    s = (line or "").strip()
                    if s:
                        self.update_log(s)
        except Exception:
            return

    def _ensure_service_log_poller(self):
        if self._service_log_event is not None:
            return
        try:
            self._service_log_event = Clock.schedule_interval(self._poll_service_log, 1.0)
        except Exception:
            self._service_log_event = None

    def _stop_service_log_poller(self):
        try:
            if self._service_log_event is not None:
                self._service_log_event.cancel()
        except Exception:
            pass
        self._service_log_event = None

    def _maybe_start_in_app_fallback(self, reason):
        try:
            if not os.environ.get("ANDROID_PRIVATE"):
                return
            self.update_log(f"{reason}")
        except Exception:
            pass

    def _check_service_started(self, dt=0):
        self._service_start_check_event = None
        p = self._service_log_path
        if not p:
            self._maybe_start_in_app_fallback("Service log unavailable, fallback to in-app background thread.")
            return
        try:
            if not os.path.exists(p):
                self._maybe_start_in_app_fallback("Service log file not found, fallback to in-app background thread.")
                return
            size = int(os.path.getsize(p) or 0)
            if size <= int(self._service_log_baseline_size or 0):
                self._maybe_start_in_app_fallback("Service produced no log output, fallback to in-app background thread.")
        except Exception:
            self._maybe_start_in_app_fallback("Service check failed, fallback to in-app background thread.")

    def _wait_service_ready_and_move_home(self):
        try:
            baseline = 0
            try:
                baseline = int(self._service_log_baseline_size or 0)
            except Exception:
                baseline = 0
            start = time.monotonic()
            while (time.monotonic() - start) < 8.0:
                try:
                    p = self._service_log_path
                    if p and os.path.exists(p):
                        sz = int(os.path.getsize(p) or 0)
                        if sz > baseline:
                            break
                except Exception:
                    pass
                time.sleep(0.2)
        except Exception:
            pass

        service_ok = False
        try:
            p = self._service_log_path
            if p and os.path.exists(p) and int(os.path.getsize(p) or 0) > 0:
                service_ok = True
        except Exception:
            service_ok = False

        if not service_ok:
            self._maybe_start_in_app_fallback("Service not ready, keep app in foreground.")
            return

        try:
            self._force_move_to_home_background(0)
        except Exception:
            try:
                Clock.schedule_once(self._force_move_to_home_background, 0)
            except Exception:
                pass

    def _move_to_home_background(self, dt=0):
        if not os.environ.get("ANDROID_PRIVATE"):
            return
        now = time.monotonic()
        if now - (self._last_move_home_at or 0.0) < 2.0:
            return
        self._last_move_home_at = now
        try:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity

            Intent = autoclass("android.content.Intent")
            intent = Intent(Intent.ACTION_MAIN)
            intent.addCategory(Intent.CATEGORY_HOME)
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
        except Exception:
            pass
        try:
            p = self._capture_ready_path
            if p:
                with open(p, "w", encoding="utf-8", errors="ignore") as f:
                    f.write(str(time.time() + 1.0))
        except Exception:
            pass
        try:
            self._capture_ready_armed = False
        except Exception:
            pass

    def update_log(self, message):
        # Schedule update on main thread
        Clock.schedule_once(lambda dt: self._append_log(message))

    def _append_log(self, message):
        item = ChatListItem(text=str(message), is_user=False, font_name=self._cjk_font)
        self.chat_list.add_widget(item)
        if len(self.chat_list.children) > 100:
            self.chat_list.remove_widget(self.chat_list.children[-1])
        Clock.schedule_once(lambda dt: setattr(self.scroll_view, 'scroll_y', 0), 0.1)

    def _poll_inbox_task(self, dt=0):
        if self._manual_task_running:
            return
        paths = getattr(self, "_inbox_task_paths", None)
        if not paths:
            return
        try:
            for p in list(paths or []):
                if not p:
                    continue
                if not os.path.exists(p):
                    continue
                try:
                    print(f"[Inbox] Detected inbox file: {p}")
                except Exception:
                    pass
                if os.path.getsize(p) > 200000:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                    self.update_log("Inbox task file too large, dropped.")
                    return
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    raw = (f.read() or "").strip()
                if not raw:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                    continue
                task_text = ""
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        task_text = (obj.get("task") or obj.get("text") or "").strip()
                    else:
                        task_text = str(obj).strip()
                except Exception:
                    task_text = raw
                if not task_text:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                    continue
                try:
                    print(f"[Inbox] Task received ({len(task_text)} chars)")
                except Exception:
                    pass
                self._run_inbox_task(task_text)
                try:
                    os.remove(p)
                except Exception:
                    pass
                return
        except Exception:
            return

    def _run_inbox_task(self, task_text):
        t = (str(task_text) if task_text is not None else "").strip()
        if not t:
            return
        try:
            self.msg_input.text = ""
        except Exception:
            pass
        try:
            item = ChatListItem(text=t, is_user=True, font_name=self._cjk_font)
            self.chat_list.add_widget(item)
            Clock.schedule_once(lambda dt: setattr(self.scroll_view, 'scroll_y', 0), 0.1)
        except Exception:
            pass
        self._start_manual_task(t)

    def _run_manual_task_thread(self, task_text, task_id):
        try:
            ret = self.backend.run_manual_task(task_text, task_id=task_id)
            try:
                self.update_log(f"Task Finished: {json.dumps(ret, ensure_ascii=False)}")
            except Exception:
                self.update_log(f"Task Finished: {ret!r}")
        except Exception as e:
            try:
                self.update_log(f"Task Failed: {e}\n{traceback.format_exc()}")
            except Exception:
                self.update_log(f"Task Failed: {e}")
        finally:
            Clock.schedule_once(lambda dt: self._finish_manual_task(), 0)

    def _finish_manual_task(self):
        self._manual_task_running = False
        self._manual_task_thread = None
        self.btn_start.disabled = False
        self.btn_start.opacity = 1.0
        self.btn_stop.disabled = True
        self.btn_stop.opacity = 0.5
        self.btn_send.disabled = False
        if self.is_voice_mode:
            self.btn_send_color.rgba = (0.2, 0.6, 1, 1)
        else:
            self.on_text_change(self.msg_input, self.msg_input.text)

    def _start_manual_task(self, task_text):
        now = time.monotonic()
        if now - (self._last_start_query_at or 0.0) < 1.0:
            return
        self._last_start_query_at = now

        if self._manual_task_running:
            self.update_log("已有任务正在执行，请先停止或等待完成。")
            return

        self.btn_start.disabled = True
        self.btn_start.opacity = 0.5
        self.btn_stop.disabled = False
        self.btn_stop.opacity = 1.0
        self.btn_send.disabled = True
        self.btn_send_color.rgba = (0.8, 0.8, 0.8, 1)
        self._manual_task_running = True

        should_move_home = True
        if os.environ.get("ANDROID_PRIVATE"):
            try:
                p = self._capture_ready_path
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
            try:
                prompted = bool(request_ignore_battery_optimizations())
                if prompted:
                    should_move_home = False
                    self.update_log("请先完成电池优化授权弹窗，完成后将自动返回桌面。")
                    self._pending_battery_permission = True
                    self._start_permission_watcher()
            except Exception:
                pass
            try:
                from jnius import autoclass

                Build_VERSION = autoclass("android.os.Build$VERSION")
                sdk_int = int(getattr(Build_VERSION, "SDK_INT", 0) or 0)
                if sdk_int >= 33:
                    try:
                        from android.permissions import Permission, check_permission, request_permissions

                        if not check_permission(Permission.POST_NOTIFICATIONS):
                            should_move_home = False
                            self.update_log("请先完成通知权限授权弹窗，完成后将自动返回桌面。")
                            self._pending_notification_permission = True
                            self._start_permission_watcher()
                            try:
                                def _perm_cb(*args, **kwargs):
                                    try:
                                        ok = check_permission(Permission.POST_NOTIFICATIONS)
                                        self.update_log(f"通知权限状态: {ok}")
                                    except Exception:
                                        ok = False
                                    try:
                                        self._pending_notification_permission = False if ok else True
                                        self._start_permission_watcher()
                                    except Exception:
                                        pass
                                request_permissions([Permission.POST_NOTIFICATIONS], _perm_cb)
                            except Exception:
                                request_permissions([Permission.POST_NOTIFICATIONS])
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                adb_status = None
                try:
                    from scripts.and_controller import get_adb_status
                    adb_status = str(get_adb_status() or "")
                except Exception:
                    try:
                        from and_controller import get_adb_status
                        adb_status = str(get_adb_status() or "")
                    except Exception:
                        adb_status = ""

                if adb_status != "ready":
                    should_move_home = False
                    self._pending_adb_authorization = True
                    self._pending_adb_since = time.monotonic()
                    self._adb_status_last = None
                    self._start_permission_watcher()
            except Exception:
                pass

        task_id = int(time.time() * 1000)
        self.update_log(f"Task Started: {task_text}")
        self._manual_task_thread = threading.Thread(
            target=self._run_manual_task_thread,
            args=(task_text, task_id),
            daemon=True,
        )
        self._manual_task_thread.start()

        try:
            if self._move_home_event is not None:
                self._move_home_event.cancel()
        except Exception:
            pass
        if os.environ.get("ANDROID_PRIVATE") and (not should_move_home):
            self._move_home_event = None
            return
        self._move_home_event = Clock.schedule_once(self._move_to_home_background, 2.0)

    def start_query(self, instance, task_text=None):
        t = (str(task_text).strip() if task_text is not None else "")
        if not t:
            try:
                t = (self.msg_input.text or "").strip()
            except Exception:
                t = ""
        if not t:
            return
        self._start_manual_task(t)

    def stop_query(self, instance):
        try:
            if os.environ.get("ANDROID_PRIVATE"):
                self._stop_android_service()
                self._stop_service_log_poller()
                self._stop_permission_watcher()
                self._pending_notification_permission = False
                self._pending_battery_permission = False
                self._pending_adb_authorization = False
                self._pending_adb_since = 0.0
                try:
                    p = self._capture_ready_path
                    if p and os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
            else:
                self.backend.stop_query_thread()
        except Exception:
            pass
        try:
            self.backend.stop_event.set()
        except Exception:
            pass
        try:
            if self._move_home_event is not None:
                self._move_home_event.cancel()
        except Exception:
            pass
        self._move_home_event = None
        self._manual_task_running = False
        self._manual_task_thread = None
        self.btn_start.disabled = False
        self.btn_start.opacity = 1.0
        self.btn_stop.disabled = True
        self.btn_stop.opacity = 0.5
        self.btn_send.disabled = False
        if self.is_voice_mode:
            self.btn_send_color.rgba = (0.2, 0.6, 1, 1)
        else:
            self.on_text_change(self.msg_input, self.msg_input.text)
        self.update_log("Task Stopping...")

    def clear_log(self, instance):
        self.chat_list.clear_widgets()

if __name__ == '__main__':
    OrderQueryApp().run()
