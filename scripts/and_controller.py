import os
import subprocess
import base64
import xml.etree.ElementTree as ET
import time
import sys
import platform
import shutil
import re
import shlex
import socket
import traceback
import threading
import logging

# Try importing adb_shell for Android support
ADB_SHELL_AVAILABLE = False
ADB_SHELL_IMPORT_ERROR = None
try:
    from adb_shell.adb_device import AdbDeviceTcp
    from adb_shell.auth.keygen import keygen
    from adb_shell.auth.sign_pythonrsa import PythonRSASigner
    ADB_SHELL_AVAILABLE = True
except ImportError as e:
    ADB_SHELL_IMPORT_ERROR = f"{e}\n{traceback.format_exc()}"

try:
    from config import load_config
except Exception:
    from scripts.config import load_config

try:
    from utils import print_with_color
except Exception:
    from scripts.utils import print_with_color


configs = load_config()

try:
    for _name in [
        "adb_shell",
        "adb_shell.adb_device",
        "adb_shell.transport",
        "adb_shell.transport.tcp_transport",
    ]:
        logging.getLogger(_name).setLevel(logging.WARNING)
except Exception:
    pass

# Global ADB connection for Android
android_adb_device = None
android_adb_target = None
android_adb_last_error = None
android_adb_last_command = None
android_adb_next_connect_at = 0.0
_adb_setup_lock = threading.Lock()
_adb_status_last = None
_adb_status_next_check_at = 0.0

def _is_android():
    return platform.machine() in ['aarch64', 'armv7l']

def _parse_adb_tcp_target(device):
    if device is None:
        return None
    d = str(device).strip()
    if not d:
        return None
    if d.startswith("tcp:"):
        d = d[4:]
    if ":" in d:
        host, port_str = d.rsplit(":", 1)
        host = host.strip()
        port_str = port_str.strip()
        if host and port_str.isdigit():
            port = int(port_str)
            if 1 <= port <= 65535:
                return host, port, f"{host}:{port}"
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", d):
        return d, 5555, f"{d}:5555"
    return None

def _default_android_target():
    host = (configs.get("ANDROID_ADB_HOST") or configs.get("ADB_HOST") or "").strip()
    port_str = str(configs.get("ANDROID_ADB_PORT") or configs.get("ADB_PORT") or "").strip()
    if host:
        port = 5555
        if port_str.isdigit():
            parsed = int(port_str)
            if 1 <= parsed <= 65535:
                port = parsed
        return host, port, f"{host}:{port}"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("1.1.1.1", 80))
            ip = (s.getsockname()[0] or "").strip()
        finally:
            try:
                s.close()
            except Exception:
                pass
        if ip and ip != "127.0.0.1":
            return ip, 5555, f"{ip}:5555"
    except Exception:
        pass
    return "127.0.0.1", 5555, "127.0.0.1:5555"

def _iter_android_targets(preferred_device=None):
    seen = set()

    parsed = _parse_adb_tcp_target(preferred_device)
    if parsed:
        _host, _port, target = parsed
        if target not in seen:
            seen.add(target)
            yield parsed

    target_str = (configs.get("ANDROID_ADB_TARGET") or configs.get("ADB_TARGET") or "").strip()
    parsed = _parse_adb_tcp_target(target_str) if target_str else None
    if parsed:
        _host, _port, target = parsed
        if target not in seen:
            seen.add(target)
            yield parsed

    host, port, target = _default_android_target()
    if target not in seen:
        seen.add(target)
        yield host, port, target

class AndroidElement:
    def __init__(self, uid, bbox, attrib):
        self.uid = uid
        self.bbox = bbox
        self.attrib = attrib

def setup_adb_connection(preferred_device=None):
    global android_adb_device, android_adb_target, android_adb_last_error
    global android_adb_next_connect_at
    if not ADB_SHELL_AVAILABLE:
        android_adb_last_error = f"adb_shell not available: {ADB_SHELL_IMPORT_ERROR}" if ADB_SHELL_IMPORT_ERROR else "adb_shell not available"
        print_with_color("adb_shell not available", "red")
        return None

    now = time.monotonic()
    if now < float(android_adb_next_connect_at or 0.0):
        return None

    debug_enabled = (os.environ.get("ORDERQUERY_DEBUG") or "").strip() == "1"
    with _adb_setup_lock:
        now = time.monotonic()
        if now < float(android_adb_next_connect_at or 0.0):
            return None
    
        is_android = _is_android()
        base_dir = os.environ.get("ANDROID_PRIVATE") if is_android else None
        if not base_dir:
            base_dir = os.path.expanduser("~") if is_android else os.getcwd()
        try:
            os.makedirs(base_dir, exist_ok=True)
        except Exception:
            pass

        key_path = os.path.abspath(os.path.join(base_dir, 'adbkey'))

        priv_exists = os.path.exists(key_path)
        pub_exists = os.path.exists(key_path + ".pub")
        force_regen = False

        if priv_exists != pub_exists:
            force_regen = True
        elif priv_exists and pub_exists:
            try:
                with open(key_path, 'rb') as f:
                    priv_content = f.read()
                with open(key_path + ".pub", 'rb') as f:
                    pub_content = f.read()
                if b"-----BEGIN" not in priv_content or b"-----END" not in priv_content or len(priv_content) < 256 or len(pub_content) < 32:
                    force_regen = True
            except Exception:
                force_regen = True

        if force_regen:
            try:
                if priv_exists:
                    os.remove(key_path)
                if pub_exists:
                    os.remove(key_path + ".pub")
            except Exception:
                pass

        if (not os.path.exists(key_path)) or (not os.path.exists(key_path + ".pub")):
            try:
                if debug_enabled:
                    print_with_color("Generating new ADB keys...", "yellow")
                keygen(key_path)
            except Exception as e:
                android_adb_last_error = str(e)
                return None

        try:
            with open(key_path, 'r', encoding='utf-8') as f:
                priv = f.read().strip()
            with open(key_path + '.pub', 'r', encoding='utf-8') as f:
                pub = f.read().strip()

            signer = PythonRSASigner(pub, priv)

            last_error = None
            for host, port, target in _iter_android_targets(preferred_device=preferred_device):
                if android_adb_device is not None and android_adb_target == target:
                    return android_adb_device

                try:
                    if debug_enabled:
                        print_with_color(f"Connecting to {target}...", "yellow")
                    device = AdbDeviceTcp(host, port, default_transport_timeout_s=60.0)
                    device.connect(rsa_keys=[signer], auth_timeout_s=60.0)
                    android_adb_device = device
                    android_adb_target = target
                    android_adb_last_error = None
                    if debug_enabled:
                        print_with_color(f"Connected to {target}", "green")
                    return device
                except Exception as e:
                    last_error = e
                    android_adb_last_error = str(e)
                    continue
            raise last_error if last_error else Exception("No ADB target candidates")
        except Exception as e:
            android_adb_last_error = str(e)
            s = str(e).lower()
            if ("unauthorized" in s) or ("auth" in s) or ("denied" in s) or ("permission" in s):
                android_adb_next_connect_at = time.monotonic() + 30.0
            return None

def execute_adb(adb_command):
    # Check if running on Android (arm/aarch64)
    is_android = _is_android()
    
    if is_android:
        global android_adb_device, android_adb_target, android_adb_last_error, android_adb_last_command
        global android_adb_next_connect_at
        android_adb_last_command = str(adb_command)
        if not ADB_SHELL_AVAILABLE:
            android_adb_last_error = f"adb_shell not available: {ADB_SHELL_IMPORT_ERROR}" if ADB_SHELL_IMPORT_ERROR else "adb_shell not available"
            return "ERROR"
        if time.monotonic() < float(android_adb_next_connect_at or 0.0):
            return "ERROR"
        if not android_adb_device:
            try:
                setup_adb_connection()
            except Exception as e:
                android_adb_last_error = f"{e}\n{traceback.format_exc()}"
                android_adb_device = None
        
        if not android_adb_device:
             # Only log error if not a simple check
             if "devices" not in adb_command:
                android_adb_last_error = android_adb_last_error or "No ADB connection available on Android. Ensure 'adb tcpip 5555' was run via USB."
                print_with_color("No ADB connection available on Android. Ensure 'adb tcpip 5555' was run via USB.", "red")
             return "ERROR"

        try:
            parts = shlex.split(adb_command)
        except:
            parts = adb_command.split()

        if "-s" in parts:
            try:
                idx = parts.index("-s")
                maybe_device = parts[idx + 1] if idx + 1 < len(parts) else None
            except Exception:
                maybe_device = None
            parsed = _parse_adb_tcp_target(maybe_device)
            if parsed:
                _host, _port, target = parsed
                if android_adb_target != target:
                    try:
                        setup_adb_connection(preferred_device=maybe_device)
                    except Exception:
                        return "ERROR"

        # Simple parser for supported commands
        if 'shell' in parts:
            try:
                # Regex to extract everything after 'shell'
                match = re.search(r'shell\s+(.*)', adb_command, re.DOTALL)
                if match:
                    shell_cmd = match.group(1)
                    # Handle escaped quotes for text input if needed, but adb_shell expects raw string
                    # If shell_cmd starts with quotes, we might need to strip them if they were for the shell wrapper
                    # But usually adb -s x shell "cmd" -> cmd
                    # shlex.split would have removed outer quotes.
                    # Re-constructing from parts might be safer?
                    # No, parts loses spacing.
                    
                    # For complex commands like "input text 'hello world'", shell_cmd is "input text 'hello world'"
                    try:
                        out = android_adb_device.shell(shell_cmd)
                        android_adb_last_error = None
                        return (out or "").strip()
                    except Exception as e:
                        android_adb_last_error = f"{e}\n{traceback.format_exc()}"
                        try:
                            setup_adb_connection(preferred_device=android_adb_target)
                            out = android_adb_device.shell(shell_cmd)
                            android_adb_last_error = None
                            return (out or "").strip()
                        except Exception as e2:
                            android_adb_last_error = f"{e2}\n{traceback.format_exc()}"
                            raise
            except Exception as e:
                print_with_color(f"ADB Shell Error: {e}", "red")
                return "ERROR"
                
        elif 'pull' in parts:
             try:
                 pull_idx = parts.index('pull')
                 remote_path = parts[pull_idx + 1]
                 local_path = parts[pull_idx + 2]

                 try:
                     parent = os.path.dirname(local_path)
                     if parent:
                         os.makedirs(parent, exist_ok=True)
                 except Exception:
                     pass

                 try:
                     android_adb_device.pull(remote_path, local_path)
                     android_adb_last_error = None
                     return ""
                 except Exception as e:
                     android_adb_last_error = f"{e}\n{traceback.format_exc()}"
                     raise
             except Exception as e:
                 print_with_color(f"ADB Pull Error: {e}", "red")
                 return "ERROR"
                 
        elif 'push' in parts:
             try:
                 push_idx = parts.index('push')
                 local_path = parts[push_idx + 1]
                 remote_path = parts[push_idx + 2]

                 try:
                     with open(local_path, "rb") as f:
                         android_adb_device.push(f, remote_path)
                     android_adb_last_error = None
                     return ""
                 except Exception as e:
                     android_adb_last_error = f"{e}\n{traceback.format_exc()}"
                     raise
             except Exception as e:
                 print_with_color(f"ADB Push Error: {e}", "red")
                 return "ERROR"
        
        elif 'devices' in parts:
             target = android_adb_target or "127.0.0.1:5555"
             return f"List of devices attached\n{target}\tdevice"

        return "ERROR"

def is_adb_authorization_pending(preferred_device=None):
    if not _is_android():
        return False
    if not ADB_SHELL_AVAILABLE:
        return False
    try:
        base_dir = os.environ.get("ANDROID_PRIVATE") or os.path.expanduser("~") or os.getcwd()
        try:
            os.makedirs(base_dir, exist_ok=True)
        except Exception:
            pass

        key_path = os.path.abspath(os.path.join(base_dir, 'adbkey'))
        if (not os.path.exists(key_path)) or (not os.path.exists(key_path + ".pub")):
            try:
                keygen(key_path)
            except Exception:
                return False

        with open(key_path, 'r', encoding='utf-8') as f:
            priv = f.read().strip()
        with open(key_path + '.pub', 'r', encoding='utf-8') as f:
            pub = f.read().strip()
        signer = PythonRSASigner(pub, priv)

        for host, port, target in _iter_android_targets(preferred_device=preferred_device):
            try:
                device = AdbDeviceTcp(host, port, default_transport_timeout_s=1.0)
                device.connect(rsa_keys=[signer], auth_timeout_s=0.2)
                return False
            except Exception as e:
                s = str(e).lower()
                if ("unauthorized" in s) or ("auth" in s) or ("denied" in s) or ("permission" in s):
                    return True
                if ("refused" in s) or ("timed out" in s) or ("timeout" in s) or ("no route" in s) or ("unreachable" in s):
                    return True
                continue
        return False
    except Exception:
        return False

def get_adb_status(preferred_device=None):
    if not _is_android():
        return "not_android"
    if not ADB_SHELL_AVAILABLE:
        return "no_adb_shell"
    global _adb_status_last, _adb_status_next_check_at
    now = time.monotonic()
    if now < float(_adb_status_next_check_at or 0.0) and _adb_status_last:
        return _adb_status_last
    try:
        base_dir = os.environ.get("ANDROID_PRIVATE") or os.path.expanduser("~") or os.getcwd()
        try:
            os.makedirs(base_dir, exist_ok=True)
        except Exception:
            pass

        key_path = os.path.abspath(os.path.join(base_dir, 'adbkey'))
        if (not os.path.exists(key_path)) or (not os.path.exists(key_path + ".pub")):
            try:
                keygen(key_path)
            except Exception as e:
                return f"keygen_error:{e}"

        with open(key_path, 'r', encoding='utf-8') as f:
            priv = f.read().strip()
        with open(key_path + '.pub', 'r', encoding='utf-8') as f:
            pub = f.read().strip()
        signer = PythonRSASigner(pub, priv)

        for host, port, target in _iter_android_targets(preferred_device=preferred_device):
            try:
                device = AdbDeviceTcp(host, port, default_transport_timeout_s=1.0)
                device.connect(rsa_keys=[signer], auth_timeout_s=0.2)
                try:
                    device.close()
                except Exception:
                    pass
                return "ready"
            except Exception as e:
                s = str(e).lower()
                if ("unauthorized" in s) or ("auth" in s) or ("denied" in s) or ("permission" in s):
                    _adb_status_last = "unauthorized"
                    _adb_status_next_check_at = time.monotonic() + 6.0
                    return _adb_status_last
                if ("refused" in s) or ("timed out" in s) or ("timeout" in s) or ("no route" in s) or ("unreachable" in s):
                    _adb_status_last = "unreachable"
                    _adb_status_next_check_at = time.monotonic() + 6.0
                    return _adb_status_last
                _adb_status_last = f"error:{s[:120]}"
                _adb_status_next_check_at = time.monotonic() + 6.0
                return _adb_status_last
        _adb_status_last = "unreachable"
        _adb_status_next_check_at = time.monotonic() + 6.0
        return _adb_status_last
    except Exception as e:
        _adb_status_last = f"error:{e}"
        _adb_status_next_check_at = time.monotonic() + 6.0
        return _adb_status_last

    # PC / Standard execution
    # print(adb_command)
    try:
        result = subprocess.run(adb_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        if result.returncode == 0 and result.stdout is not None:
            return result.stdout.strip()
        print_with_color(f"Command execution failed: {adb_command}", "red")
        if result.stderr:
            print_with_color(result.stderr, "red")
        return "ERROR"
    except Exception as e:
        print_with_color(f"Exception during ADB command execution: {adb_command}", "red")
        print_with_color(str(e), "red")
        return "ERROR"


def list_all_devices(preferred_device=None):
    is_android = _is_android()
    if is_android:
        global android_adb_device, android_adb_target
        if not android_adb_device:
            try:
                setup_adb_connection(preferred_device=preferred_device)
            except Exception:
                return []
        if android_adb_device:
            return [android_adb_target or "127.0.0.1:5555"]
        return []

    adb_command = "adb devices"
    device_list = []
    result = execute_adb(adb_command)
    if result != "ERROR":
        devices = result.split("\n")[1:]
        for d in devices:
            if d.strip():  # 确保不是空行
                device_info = d.split()
                if len(device_info) >= 2 and device_info[1] == "device":
                    device_list.append(device_info[0])
    else:
        # ADB命令执行失败，可能是ADB未安装
        print_with_color("ADB command failed. Please ensure Android Debug Bridge is installed.", "red")
        raise Exception("ADB not found. Please install Android Debug Bridge and ensure it's in your PATH.")

    return device_list


def get_id_from_element(elem):
    bounds = elem.attrib["bounds"][1:-1].split("][")
    x1, y1 = map(int, bounds[0].split(","))
    x2, y2 = map(int, bounds[1].split(","))
    elem_w, elem_h = x2 - x1, y2 - y1
    if "resource-id" in elem.attrib and elem.attrib["resource-id"]:
        elem_id = elem.attrib["resource-id"].replace(":", ".").replace("/", "_")
    else:
        elem_id = f"{elem.attrib['class']}_{elem_w}_{elem_h}"
    if "content-desc" in elem.attrib and elem.attrib["content-desc"] and len(elem.attrib["content-desc"]) < 20:
        content_desc = elem.attrib['content-desc'].replace("/", "_").replace(" ", "").replace(":", "_")
        elem_id += f"_{content_desc}"
    return elem_id


def traverse_tree(xml_path, elem_list, attrib, add_index=False):
    path = []
    for event, elem in ET.iterparse(xml_path, ['start', 'end']):
        if event == 'start':
            path.append(elem)
            if attrib in elem.attrib and elem.attrib[attrib] == "true":
                parent_prefix = ""
                if len(path) > 1:
                    parent_prefix = get_id_from_element(path[-2])
                bounds = elem.attrib["bounds"][1:-1].split("][")
                x1, y1 = map(int, bounds[0].split(","))
                x2, y2 = map(int, bounds[1].split(","))
                center = (x1 + x2) // 2, (y1 + y2) // 2
                elem_id = get_id_from_element(elem)
                if parent_prefix:
                    elem_id = parent_prefix + "_" + elem_id
                if add_index:
                    elem_id += f"_{elem.attrib['index']}"
                close = False
                for e in elem_list:
                    bbox = e.bbox
                    center_ = (bbox[0][0] + bbox[1][0]) // 2, (bbox[0][1] + bbox[1][1]) // 2
                    dist = (abs(center[0] - center_[0]) ** 2 + abs(center[1] - center_[1]) ** 2) ** 0.5
                    if dist <= configs["MIN_DIST"]:
                        close = True
                        break
                if not close:
                    elem_list.append(AndroidElement(elem_id, ((x1, y1), (x2, y2)), attrib))

        if event == 'end':
            path.pop()

def _extract_shell_rc(output):
    try:
        s = str(output) if output is not None else ""
    except Exception:
        return None
    if not s:
        return None
    m = re.search(r"__RC:(-?\d+)", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def _looks_like_png(raw_bytes):
    try:
        if not raw_bytes or len(raw_bytes) < 8:
            return False
        return raw_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    except Exception:
        return False

def _looks_like_uiautomator_xml(text):
    try:
        s = str(text) if text is not None else ""
    except Exception:
        return False
    s = s.lstrip()
    if not s:
        return False
    if s.startswith("<?xml"):
        return True
    if s.startswith("<hierarchy"):
        return True
    return False


class AndroidController:
    def __init__(self, device):
        self.device = device
        self.screenshot_dir = configs["ANDROID_SCREENSHOT_DIR"]
        self.xml_dir = configs["ANDROID_XML_DIR"]
        self.width, self.height = self.get_device_size()
        self.backslash = "\\"
        self._ensure_remote_tmp_dirs()

    def _ensure_remote_tmp_dirs(self):
        try:
            screenshot_dir = (self.screenshot_dir or "").strip()
            xml_dir = (self.xml_dir or "").strip()
            if screenshot_dir:
                execute_adb(f"adb -s {self.device} shell sh -c \"mkdir -p '{screenshot_dir}'; : > '{screenshot_dir}/.nomedia'\"")
            if xml_dir:
                execute_adb(f"adb -s {self.device} shell sh -c \"mkdir -p '{xml_dir}'; : > '{xml_dir}/.nomedia'\"")
        except Exception:
            pass

    def get_device_size(self):
        def _query():
            adb_command = f"adb -s {self.device} shell wm size"
            result = execute_adb(adb_command)
            if result != "ERROR":
                m = re.search(r"(\d+)\s*x\s*(\d+)", result)
                if m:
                    return int(m.group(1)), int(m.group(2))
            return 0, 0

        width, height = _query()
        if width and height:
            return width, height

        if _is_android():
            try:
                setup_adb_connection(preferred_device=self.device)
            except Exception:
                pass
            width, height = _query()
            if width and height:
                return width, height
            try:
                from jnius import autoclass
                DisplayMetrics = autoclass("android.util.DisplayMetrics")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                metrics = DisplayMetrics()
                display = activity.getWindowManager().getDefaultDisplay()
                try:
                    display.getRealMetrics(metrics)
                except Exception:
                    display.getMetrics(metrics)
                w = int(getattr(metrics, "widthPixels", 0) or 0)
                h = int(getattr(metrics, "heightPixels", 0) or 0)
                if w > 0 and h > 0:
                    return w, h
            except Exception:
                pass

        return 0, 0

    def get_screenshot(self, prefix, save_dir):
        remote_path = os.path.join(self.screenshot_dir, prefix + '.png').replace(self.backslash, '/')
        local_path = os.path.join(save_dir, prefix + '.png')
        cap_command = f"adb -s {self.device} shell sh -c \"screencap -p '{remote_path}'; echo __RC:$?\""
        pull_command = f"adb -s {self.device} pull " \
                       f"{remote_path} " \
                       f"{local_path}"
        rm_command = f"adb -s {self.device} shell rm -f '{remote_path}'"
        trace_capture = (os.environ.get("ORDERQUERY_TRACE_CAPTURE") or "").strip() == "1"
        if trace_capture:
            print_with_color(f"[CAPTURE] screenshot begin prefix={prefix}", "yellow")
            print_with_color(f"[CAPTURE] screenshot cap_cmd={cap_command}", "yellow")
        result = execute_adb(cap_command)
        if result != "ERROR":
            rc = _extract_shell_rc(result)
            if rc is not None and rc != 0:
                if trace_capture:
                    print_with_color(f"[CAPTURE] screenshot cap_rc={rc} prefix={prefix}", "red")
                return "ERROR"
            if trace_capture:
                print_with_color(f"[CAPTURE] screenshot cap_ok prefix={prefix}", "yellow")
            if _is_android():
                b64_command = f"adb -s {self.device} shell sh -c \"base64 -w 0 '{remote_path}'\""
                if trace_capture:
                    print_with_color(f"[CAPTURE] screenshot b64_cmd={b64_command}", "yellow")
                b64_out = execute_adb(b64_command)
                if b64_out != "ERROR":
                    try:
                        raw = base64.b64decode((b64_out or "").encode("ascii", errors="ignore"), validate=False)
                        if raw and _looks_like_png(raw):
                            try:
                                parent = os.path.dirname(local_path)
                                if parent:
                                    os.makedirs(parent, exist_ok=True)
                            except Exception:
                                pass
                            with open(local_path, "wb") as f:
                                f.write(raw)
                            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                                if trace_capture:
                                    print_with_color(f"[CAPTURE] screenshot b64_ok prefix={prefix} size={os.path.getsize(local_path)}", "yellow")
                                    print_with_color(f"[CAPTURE] screenshot rm_cmd={rm_command}", "yellow")
                                execute_adb(rm_command)
                                return local_path
                    except Exception as e:
                        if trace_capture:
                            print_with_color(f"[CAPTURE] screenshot b64_decode_error prefix={prefix} err={e}", "red")

            if trace_capture:
                print_with_color(f"[CAPTURE] screenshot pull_cmd={pull_command}", "yellow")
            result = execute_adb(pull_command)
            if result != "ERROR":
                try:
                    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                        if trace_capture:
                            print_with_color(f"[CAPTURE] screenshot pull_ok prefix={prefix} size={os.path.getsize(local_path)}", "yellow")
                            print_with_color(f"[CAPTURE] screenshot rm_cmd={rm_command}", "yellow")
                        execute_adb(rm_command)
                        return local_path
                except Exception:
                    pass
                return "ERROR"
            return result
        return result

    def get_xml(self, prefix, save_dir):
        remote_path = os.path.join(self.xml_dir, prefix + '.xml').replace(self.backslash, '/')
        local_path = os.path.join(save_dir, prefix + '.xml')
        dump_command = f"adb -s {self.device} shell sh -c \"uiautomator dump '{remote_path}'; echo __RC:$?\""
        pull_command = f"adb -s {self.device} pull {remote_path} {local_path}"
        rm_command = f"adb -s {self.device} shell rm -f '{remote_path}'"
        trace_capture = (os.environ.get("ORDERQUERY_TRACE_CAPTURE") or "").strip() == "1"
        if trace_capture:
            print_with_color(f"[CAPTURE] xml begin prefix={prefix}", "yellow")
            print_with_color(f"[CAPTURE] xml dump_cmd={dump_command}", "yellow")
        result = execute_adb(dump_command)

        if result != "ERROR":
            rc = _extract_shell_rc(result)
            if rc is not None and rc != 0:
                if trace_capture:
                    print_with_color(f"[CAPTURE] xml dump_rc={rc} prefix={prefix}", "red")
                return "ERROR"
            if trace_capture:
                print_with_color(f"[CAPTURE] xml dump_ok prefix={prefix}", "yellow")
            if _is_android():
                cat_command = f"adb -s {self.device} shell sh -c \"cat '{remote_path}'\""
                if trace_capture:
                    print_with_color(f"[CAPTURE] xml cat_cmd={cat_command}", "yellow")
                xml_out = execute_adb(cat_command)
                if xml_out != "ERROR":
                    if not _looks_like_uiautomator_xml(xml_out):
                        if trace_capture:
                            snippet = str(xml_out)[:200].replace("\n", " ")
                            print_with_color(f"[CAPTURE] xml invalid_content prefix={prefix} head={snippet}", "red")
                        return "ERROR"
                    try:
                        try:
                            parent = os.path.dirname(local_path)
                            if parent:
                                os.makedirs(parent, exist_ok=True)
                        except Exception:
                            pass
                        with open(local_path, "w", encoding="utf-8", errors="ignore") as f:
                            f.write(str(xml_out or ""))
                        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                            if trace_capture:
                                print_with_color(f"[CAPTURE] xml cat_ok prefix={prefix} size={os.path.getsize(local_path)}", "yellow")
                                print_with_color(f"[CAPTURE] xml rm_cmd={rm_command}", "yellow")
                            execute_adb(rm_command)
                            return local_path
                    except Exception as e:
                        if trace_capture:
                            print_with_color(f"[CAPTURE] xml cat_write_error prefix={prefix} err={e}", "red")

            if trace_capture:
                print_with_color(f"[CAPTURE] xml pull_cmd={pull_command}", "yellow")
            result = execute_adb(pull_command)
            if result != "ERROR":
                try:
                    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                        if trace_capture:
                            print_with_color(f"[CAPTURE] xml pull_ok prefix={prefix} size={os.path.getsize(local_path)}", "yellow")
                            print_with_color(f"[CAPTURE] xml rm_cmd={rm_command}", "yellow")
                        execute_adb(rm_command)
                        return local_path
                except Exception:
                    pass
                return "ERROR"
            return result
        return result


    def back(self):
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_BACK"
        ret = execute_adb(adb_command)
        return ret

    def home(self):
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_HOME"
        ret = execute_adb(adb_command)
        return ret

    def tap(self, x, y):
        adb_command = f"adb -s {self.device} shell input tap {x} {y}"
        ret = execute_adb(adb_command)
        return ret

    def text(self, input_str):
        # 检查是否包含中文字符
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in input_str)
        
        if has_chinese:
            # 对文本进行转义，避免shell解析问题
            # 使用单引号包裹整个命令，避免双引号问题
            escaped_text = input_str.replace("'", "'\\''")
            
            # 使用ADB键盘输入
            adb_ime_cmd = f"adb -s {self.device} shell am broadcast -a ADB_INPUT_TEXT --es msg '{escaped_text}'"
            ret = execute_adb(adb_ime_cmd)
            
        else:
            # 对于英文字符，使用原来的方式
            input_str = input_str.replace(" ", "%s")
            input_str = input_str.replace("'", "")
            adb_command = f"adb -s {self.device} shell input text {input_str}"
            ret = execute_adb(adb_command)
        
        return ret

    def long_press(self, x, y, duration=1000):
        adb_command = f"adb -s {self.device} shell input swipe {x} {y} {x} {y} {duration}"
        ret = execute_adb(adb_command)
        return ret

    def swipe(self, x, y, direction, dist="medium", quick=False):
        unit_dist = int(self.width / 10)
        if dist == "long":
            unit_dist *= 3
        elif dist == "medium":
            unit_dist *= 2
        if direction == "up":
            offset = 0, -2 * unit_dist
        elif direction == "down":
            offset = 0, 2 * unit_dist
        elif direction == "left":
            offset = -1 * unit_dist, 0
        elif direction == "right":
            offset = unit_dist, 0
        else:
            return "ERROR"
        duration = 100 if quick else 400
        adb_command = f"adb -s {self.device} shell input swipe {x} {y} {x+offset[0]} {y+offset[1]} {duration}"
        ret = execute_adb(adb_command)
        return ret

    def swipe_precise(self, start, end, duration=400):
        start_x, start_y = start
        end_x, end_y = end
        adb_command = f"adb -s {self.device} shell input swipe {start_x} {start_y} {end_x} {end_y} {duration}"
        ret = execute_adb(adb_command)
        return ret
