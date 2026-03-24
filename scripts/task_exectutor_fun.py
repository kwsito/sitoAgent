import argparse
import ast
import datetime
import json
import os
import re
import sys
import time
import logging
import platform
import socket

try:
    import prompts
except Exception:
    from scripts import prompts

try:
    from config import load_config
except Exception:
    from scripts.config import load_config

try:
    from and_controller import list_all_devices, AndroidController, traverse_tree, execute_adb
except Exception:
    from scripts.and_controller import list_all_devices, AndroidController, traverse_tree, execute_adb

try:
    from model import parse_explore_rsp, parse_grid_rsp, OpenAIModel, QwenModel, DoubaoModel
except Exception:
    from scripts.model import parse_explore_rsp, parse_grid_rsp, OpenAIModel, QwenModel, DoubaoModel

try:
    from utils import print_with_color, draw_bbox_multi, draw_grid
except Exception:
    from scripts.utils import print_with_color, draw_bbox_multi, draw_grid

try:
    from task_logger import log_to_order
except Exception:
    from scripts.task_logger import log_to_order

# 任务执行日志记录器（全局变量）
task_logger = None

def setup_task_logger(log_path):
    """配置任务执行日志记录器"""
    global task_logger
    
    try:
        # 创建logger
        task_logger = logging.getLogger(f'task_executor_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}')
        task_logger.setLevel(logging.INFO)
        
        # 避免重复添加handler
        if task_logger.handlers:
            task_logger.handlers.clear()
        
        # 创建文件handler
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # 定义日志格式
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(formatter)
        
        # 添加handler到logger
        task_logger.addHandler(file_handler)
        
        return task_logger
    except Exception as e:
        print_with_color(f"ERROR: Failed to setup logger: {e}", "red")
        return None

def log_with_color(message, color="white", level="info"):
    """
    同时记录到日志文件和控制台（带颜色）
    
    Args:
        message: 日志消息
        color: 控制台输出颜色
        level: 日志级别 (info, warning, error)
    """
    global task_logger
    
    # 打印到控制台（带颜色）
    print_with_color(message, color)
    
    # 记录到日志文件
    if task_logger:
        try:
            if level == "error":
                task_logger.error(message)
            elif level == "warning":
                task_logger.warning(message)
            else:
                task_logger.info(message)
        except Exception as e:
            print(f"Failed to log message: {e}")
    try:
        log_to_order(str(message))
    except Exception:
        pass

def area_to_xy(area, subarea, width, height, rows, cols):
        try:
            area = int(area)
        except Exception:
            area = 1

        rows = int(rows or 0)
        cols = int(cols or 0)
        width = int(width or 0)
        height = int(height or 0)
        if rows <= 0 or cols <= 0 or width <= 0 or height <= 0:
            return max(1, width // 2), max(1, height // 2)

        max_area = rows * cols
        if area < 1:
            area = 1
        if area > max_area:
            area = max_area

        area -= 1
        row, col = area // cols, area % cols
        cell_w = max(1, width // cols)
        cell_h = max(1, height // rows)
        x_0, y_0 = col * cell_w, row * cell_h

        if subarea == "top-left":
            x, y = x_0 + cell_w // 4, y_0 + cell_h // 4
        elif subarea == "top":
            x, y = x_0 + cell_w // 2, y_0 + cell_h // 4
        elif subarea == "top-right":
            x, y = x_0 + cell_w * 3 // 4, y_0 + cell_h // 4
        elif subarea == "left":
            x, y = x_0 + cell_w // 4, y_0 + cell_h // 2
        elif subarea == "right":
            x, y = x_0 + cell_w * 3 // 4, y_0 + cell_h // 2
        elif subarea == "bottom-left":
            x, y = x_0 + cell_w // 4, y_0 + cell_h * 3 // 4
        elif subarea == "bottom":
            x, y = x_0 + cell_w // 2, y_0 + cell_h * 3 // 4
        elif subarea == "bottom-right":
            x, y = x_0 + cell_w * 3 // 4, y_0 + cell_h * 3 // 4
        else:
            x, y = x_0 + cell_w // 2, y_0 + cell_h // 2

        x = max(1, min(width - 1 if width > 1 else 1, x))
        y = max(1, min(height - 1 if height > 1 else 1, y))
        return x, y

def task_exectutor(task_text, app=None, root_dir=None, log_callback=None, stop_event=None):
    args = {"app": None, "root_dir": "./"}
    try:
        arg_desc = "AppAgent Executor"
        parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=arg_desc)
        parser.add_argument("--app")
        parser.add_argument("--root_dir", default="./")
        known_args, _unknown = parser.parse_known_args(args=[])
        args = vars(known_args)
    except Exception:
        args = {"app": None, "root_dir": "./"}

    configs = load_config()

    if configs["MODEL"] == "OpenAI":
        api_key = (configs.get("OPENAI_API_KEY") or "").strip()
        if (not api_key) or api_key.lower() == "your_api_key_here":
            cfg_path = configs.get("_CONFIG_PATH") or "config.yaml"
            log_with_color(f"ERROR: OPENAI_API_KEY 未配置（配置文件: {cfg_path}），跳过自动化任务", "red", level="error")
            return {"ok": False, "skipped": True, "reason": "OPENAI_API_KEY 未配置", "config_path": cfg_path}
        mllm = OpenAIModel(base_url=configs["OPENAI_API_BASE"],
                        api_key=configs["OPENAI_API_KEY"],
                        model=configs["OPENAI_API_MODEL"],
                        temperature=configs["TEMPERATURE"],
                        max_tokens=configs["MAX_TOKENS"])
    elif configs["MODEL"] == "Qwen":
        api_key = (configs.get("DASHSCOPE_API_KEY") or "").strip()
        if not api_key:
            cfg_path = configs.get("_CONFIG_PATH") or "config.yaml"
            log_with_color(f"ERROR: DASHSCOPE_API_KEY 未配置（配置文件: {cfg_path}），跳过自动化任务", "red", level="error")
            return {"ok": False, "skipped": True, "reason": "DASHSCOPE_API_KEY 未配置", "config_path": cfg_path}
        mllm = QwenModel(api_key=configs["DASHSCOPE_API_KEY"],
                        model=configs["QWEN_MODEL"])
    elif configs["MODEL"] == "Doubao":
        api_key = (configs.get("ARK_API_KEY") or "").strip()
        api_base = (configs.get("ARK_API_BASE") or "").strip()
        api_model = (configs.get("ARK_API_MODEL") or "").strip()
        if not api_key:
            cfg_path = configs.get("_CONFIG_PATH") or "config.yaml"
            log_with_color(f"ERROR: ARK_API_KEY 未配置（配置文件: {cfg_path}），跳过自动化任务", "red", level="error")
            return {"ok": False, "skipped": True, "reason": "ARK_API_KEY 未配置", "config_path": cfg_path}
        if not api_base or not api_model:
            cfg_path = configs.get("_CONFIG_PATH") or "config.yaml"
            log_with_color(f"ERROR: ARK_API_BASE/ARK_API_MODEL 未配置（配置文件: {cfg_path}），跳过自动化任务", "red", level="error")
            return {"ok": False, "skipped": True, "reason": "ARK_API_BASE/ARK_API_MODEL 未配置", "config_path": cfg_path}
        mllm = DoubaoModel(
            base_url=api_base,
            api_key=api_key,
            model=api_model,
            temperature=configs.get("ARK_TEMPERATURE"),
            top_p=configs.get("ARK_TOP_P"),
            max_tokens=configs.get("ARK_MAX_TOKENS"),
            reasoning_effort=configs.get("ARK_REASONING_EFFORT"),
        )
    else:
        log_with_color(f"ERROR: Unsupported model type {configs['MODEL']}!", "red", level="error")
        return {"ok": False, "skipped": True, "reason": f"Unsupported model type {configs.get('MODEL')}"}

    if app is None:
        app = args.get("app")
    if root_dir is None:
        root_dir = args.get("root_dir")
    if not root_dir:
        root_dir = os.environ.get("ANDROID_PRIVATE") or "./"

    if not app:
        app = "rednote"
        app = app.replace(" ", "")

    app_dir = os.path.join(os.path.join(root_dir, "apps"), app)
    work_dir = os.path.join(root_dir, "tasks")
    if not os.path.exists(work_dir):
        try:
            os.makedirs(work_dir, exist_ok=True)
        except Exception as e:
            log_with_color(f"ERROR: 无法创建工作目录 {work_dir}: {e}", "red", level="error")
            return
    auto_docs_dir = os.path.join(app_dir, "auto_docs")
    demo_docs_dir = os.path.join(app_dir, "demo_docs")
    task_timestamp = int(time.time())
    dir_name = datetime.datetime.fromtimestamp(task_timestamp).strftime(f"task_{app}_%Y-%m-%d_%H-%M-%S")
    task_dir = os.path.join(work_dir, dir_name)
    try:
        os.makedirs(task_dir, exist_ok=True)
    except Exception as e:
        log_with_color(f"ERROR: 无法创建任务目录 {task_dir}: {e}", "red", level="error")
        return
    log_path = os.path.join(task_dir, f"log_{app}_{dir_name}.txt")
    save_task_log = (os.environ.get("ORDERQUERY_SAVE_TASK_LOG") or "").strip() == "1"
    if save_task_log:
        setup_task_logger(log_path)

    no_doc = True

    debug_enabled = (os.environ.get("ORDERQUERY_DEBUG") or "").strip() == "1"

    def _safe_remove(path):
        p = (str(path).strip() if path is not None else "")
        if not p or p == "ERROR":
            return
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    def _emit_model_rsp(step, rsp_text):
        cb = log_callback
        if not cb:
            return
        try:
            if isinstance(rsp_text, (dict, list)):
                s = json.dumps(rsp_text, ensure_ascii=False)
            elif isinstance(rsp_text, (bytes, bytearray)):
                try:
                    s = bytes(rsp_text).decode("utf-8", errors="replace")
                except Exception:
                    s = bytes(rsp_text).decode(errors="replace")
            else:
                s = str(rsp_text) if rsp_text is not None else ""
        except Exception:
            s = ""
        if not s:
            return
        try:
            if re.search(r"\\\\u[0-9a-fA-F]{4}", s):
                decoded = s.encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore")
                if decoded and (decoded.count("\\u") < s.count("\\u")):
                    s = decoded
        except Exception:
            pass
        try:
            if (not re.search(r"[\u4e00-\u9fff]", s)) and re.search(r"[\u00c0-\u00ff]", s):
                fixed = s.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
                if fixed and re.search(r"[\u4e00-\u9fff]", fixed):
                    s = fixed
        except Exception:
            pass
        if len(s) > 8000:
            s = s[:8000] + "\n...[truncated]"
        try:
            cb(f"[模型返回][step={step}]\n{s}")
        except Exception:
            pass

    is_android_runtime = platform.machine() in ["aarch64", "armv7l"]
    if is_android_runtime:
        adb_target = (configs.get("ANDROID_ADB_TARGET") or configs.get("ADB_TARGET") or "").strip()
        if not adb_target:
            host = (configs.get("ANDROID_ADB_HOST") or configs.get("ADB_HOST") or "").strip()
            port_str = str(configs.get("ANDROID_ADB_PORT") or configs.get("ADB_PORT") or "").strip()
            if host:
                port = 5555
                if port_str.isdigit():
                    parsed = int(port_str)
                    if 1 <= parsed <= 65535:
                        port = parsed
                adb_target = f"{host}:{port}"
            else:
                adb_target = "127.0.0.1:5555"
        device = adb_target
        log_with_color("ADB target resolved (android runtime).", "yellow", level="info")
    else:
        device_list = list_all_devices(None)
        if not device_list:
            log_with_color("ERROR: No device found!", "red", level="error")
            return {"ok": False, "skipped": True, "reason": "No device found"}
        log_with_color(f"Devices attached: {len(device_list)}", "yellow", level="info")
        preferred_adb_target = (configs.get("ANDROID_ADB_TARGET") or configs.get("ADB_TARGET") or "").strip()
        if preferred_adb_target and preferred_adb_target in device_list:
            device = preferred_adb_target
        else:
            device = device_list[0]
            log_with_color("Automatically selected the first available device.", "yellow", level="info")

    try:
        screenshot_dir = (configs.get("ANDROID_SCREENSHOT_DIR") or "").strip()
        xml_dir = (configs.get("ANDROID_XML_DIR") or "").strip()
        if screenshot_dir or xml_dir:
            cmd = f"adb -s {device} shell sh -c \""
            parts = []
            if screenshot_dir:
                parts.append(f"mkdir -p '{screenshot_dir}'; : > '{screenshot_dir}/.nomedia'; rm -f '{screenshot_dir}'/*.png")
            if xml_dir:
                parts.append(f"mkdir -p '{xml_dir}'; : > '{xml_dir}/.nomedia'; rm -f '{xml_dir}'/*.xml")
            cmd += "; ".join(parts) + "\""
            execute_adb(cmd)
    except Exception:
        pass
    controller = AndroidController(device)
    width, height = controller.get_device_size()
    if not width and not height:
        log_with_color("ERROR: Invalid device size!", "red", level="error")
        return {"ok": False, "skipped": True, "reason": "Invalid device size"}
    log_with_color(f"Screen resolution: {width}x{height}", "yellow", level="info")

    def _wait_capture_ready():
        if not is_android_runtime:
            return
        base_dir = os.environ.get("ANDROID_PRIVATE")
        if not base_dir:
            return
        flag_path = os.path.join(base_dir, "capture_ready.flag")
        start = time.monotonic()
        while (time.monotonic() - start) < 120.0:
            try:
                if os.path.exists(flag_path):
                    try:
                        ts = float(open(flag_path, "r", encoding="utf-8", errors="ignore").read().strip() or "0")
                    except Exception:
                        ts = 0.0
                    if ts <= 0.0:
                        return
                    if time.time() >= ts:
                        return
            except Exception:
                return
            time.sleep(0.3)
        log_with_color("WARN: capture_ready flag not found, continue capture", "yellow", level="warning")

    _wait_capture_ready()
    # Disabled automatic home screen navigation
    # try:
    #     controller.home()
    #     time.sleep(0.5)
    # except Exception:
    #     pass

    task_desc = task_text

    round_count = 0
    last_act = "None"
    task_complete = False
    grid_on = False
    rows, cols = 0, 0
    capture_failures = 0
    stop_reason = None

    def _as_int(v, default):
        try:
            return int(v)
        except Exception:
            return default

    def _as_float(v, default):
        try:
            return float(v)
        except Exception:
            return default

    max_capture_failures = _as_int(configs.get("MAX_CAPTURE_FAILURES"), 10)
    capture_retries = _as_int(configs.get("CAPTURE_RETRIES"), 3)
    capture_retry_interval = _as_float(configs.get("CAPTURE_RETRY_INTERVAL"), 1.0)

    def _get_adb_debug_state():
        try:
            import and_controller as _ac
        except Exception:
            try:
                from scripts import and_controller as _ac
            except Exception:
                return {
                    "adb_last_cmd": None,
                    "adb_last_err": None,
                    "adb_target": None,
                    "adb_shell_available": None,
                    "adb_shell_import_error": None,
                }
        return {
            "adb_last_cmd": getattr(_ac, "android_adb_last_command", None),
            "adb_last_err": getattr(_ac, "android_adb_last_error", None),
            "adb_target": getattr(_ac, "android_adb_target", None),
            "adb_shell_available": getattr(_ac, "ADB_SHELL_AVAILABLE", None),
            "adb_shell_import_error": getattr(_ac, "ADB_SHELL_IMPORT_ERROR", None),
        }

    def _log_capture_diagnostics(_device, _prefix, _task_dir, _screenshot_dir, _xml_dir):
        if not debug_enabled:
            return
        def _redact_adb_cmd(s):
            try:
                return re.sub(r"adb\s+-s\s+\S+", "adb -s <device>", str(s))
            except Exception:
                return "<redacted>"
        remote_png = os.path.join((_screenshot_dir or "").strip(), _prefix + ".png").replace("\\", "/")
        remote_xml = os.path.join((_xml_dir or "").strip(), _prefix + ".xml").replace("\\", "/")
        local_png = os.path.join(_task_dir, _prefix + ".png")
        local_xml = os.path.join(_task_dir, _prefix + ".xml")

        log_with_color("CAPTURE_DIAG_BEGIN", "yellow", level="warning")
        log_with_color("device=<redacted>", "yellow", level="warning")
        log_with_color(f"remote_png={remote_png}", "yellow", level="warning")
        log_with_color(f"remote_xml={remote_xml}", "yellow", level="warning")
        log_with_color(f"local_png_exists={os.path.exists(local_png)} size={os.path.getsize(local_png) if os.path.exists(local_png) else 0}", "yellow", level="warning")
        log_with_color(f"local_xml_exists={os.path.exists(local_xml)} size={os.path.getsize(local_xml) if os.path.exists(local_xml) else 0}", "yellow", level="warning")

        cmds = [
            f"adb -s {_device} shell id",
            f"adb -s {_device} shell getprop ro.build.version.release",
            f"adb -s {_device} shell getprop ro.build.version.sdk",
            f"adb -s {_device} shell sh -c \"command -v screencap; command -v uiautomator\"",
            f"adb -s {_device} shell ls -ld '{(_screenshot_dir or '').strip()}' '{(_xml_dir or '').strip()}'",
            f"adb -s {_device} shell ls -l '{remote_png}'",
            f"adb -s {_device} shell ls -l '{remote_xml}'",
            f"adb -s {_device} shell df -h /sdcard",
        ]
        for c in cmds:
            r = execute_adb(c)
            if r == "ERROR":
                dbg = _get_adb_debug_state()
                if dbg.get("adb_target"):
                    log_with_color("adb_target=<redacted>", "red", level="error")
                if dbg.get("adb_last_cmd"):
                    log_with_color(f"adb_last_cmd={_redact_adb_cmd(dbg.get('adb_last_cmd'))}", "red", level="error")
                if dbg.get("adb_last_err"):
                    log_with_color(f"adb_last_err={str(dbg.get('adb_last_err'))[:2000]}", "red", level="error")
                if dbg.get("adb_shell_available") is not None:
                    log_with_color(f"adb_shell_available={dbg.get('adb_shell_available')}", "red", level="error")
                if dbg.get("adb_shell_import_error"):
                    log_with_color(f"adb_shell_import_error={str(dbg.get('adb_shell_import_error'))[:2000]}", "red", level="error")
                log_with_color(f"diag_cmd={_redact_adb_cmd(c)}", "red", level="error")
            else:
                log_with_color(f"diag_cmd={_redact_adb_cmd(c)}", "yellow", level="warning")
                log_with_color(f"diag_out={str(r)[:800]}", "yellow", level="warning")

        log_with_color("CAPTURE_DIAG_END", "yellow", level="warning")

    while round_count < configs["MAX_ROUNDS"]:
        if stop_event is not None:
            try:
                if stop_event.is_set():
                    stop_reason = "stopped"
                    break
            except Exception:
                pass
        next_round = round_count + 1
        log_with_color(f"Round {next_round}", "yellow", level="info")

        prefix = f"{dir_name}_{next_round}"
        diag_logged = False
        screenshot_path = "ERROR"
        xml_path = "ERROR"
        grid_image_path = None
        labeled_image_path = None
        image = None
        for attempt in range(1, max(1, capture_retries) + 1):
            try:
                screenshot_dir = (configs.get("ANDROID_SCREENSHOT_DIR") or "").strip()
                xml_dir = (configs.get("ANDROID_XML_DIR") or "").strip()
                if screenshot_dir and xml_dir:
                    execute_adb(f"adb -s {device} shell sh -c \"mkdir -p '{screenshot_dir}' '{xml_dir}'; : > '{screenshot_dir}/.nomedia'; : > '{xml_dir}/.nomedia'\"")
            except Exception:
                pass

            t0 = time.monotonic()
            screenshot_path = controller.get_screenshot(prefix, task_dir)

            t1 = time.monotonic()
            xml_path = controller.get_xml(prefix, task_dir)
            if screenshot_path != "ERROR" and xml_path != "ERROR":
                break
            if attempt < max(1, capture_retries):
                if debug_enabled:
                    log_with_color(
                        f"Capture retry {attempt}/{max(1, capture_retries)} failed (screenshot={screenshot_path}, xml={xml_path})",
                        "yellow",
                        level="warning",
                    )
                if not diag_logged:
                    _log_capture_diagnostics(device, prefix, task_dir, screenshot_dir, xml_dir)
                    diag_logged = True
                time.sleep(max(0.0, capture_retry_interval))

        if debug_enabled:
            log_with_color(f"xml_path: {xml_path}", "yellow", level="info")
        if screenshot_path == "ERROR" or xml_path == "ERROR":
            capture_failures += 1
            log_with_color("ERROR: Failed to get screenshot or xml!", "red", level="error")
            dbg = _get_adb_debug_state()
            if dbg.get("adb_target"):
                log_with_color(f"adb_target={dbg.get('adb_target')}", "red", level="error")
            if dbg.get("adb_last_cmd"):
                log_with_color(f"adb_last_cmd={dbg.get('adb_last_cmd')}", "red", level="error")
            if dbg.get("adb_last_err"):
                log_with_color(f"adb_last_err={str(dbg.get('adb_last_err'))[:2000]}", "red", level="error")
            if dbg.get("adb_shell_available") is not None:
                log_with_color(f"adb_shell_available={dbg.get('adb_shell_available')}", "red", level="error")
            if dbg.get("adb_shell_import_error"):
                log_with_color(f"adb_shell_import_error={str(dbg.get('adb_shell_import_error'))[:2000]}", "red", level="error")
            controller.tap(int(width * 0.9), int(height * 0.9))
            log_with_color(f"获取xml失败,点击屏幕(0.9, 0.9)位置后，继续下一轮", "red", level="error")
            _safe_remove(screenshot_path)
            _safe_remove(xml_path)
            if capture_failures >= max(1, max_capture_failures):
                stop_reason = "capture_failed"
                break
            continue

        capture_failures = 0
        round_count = next_round
        if grid_on:
            grid_image_path = os.path.join(task_dir, f"{dir_name}_{round_count}_grid.png")
            rows, cols = draw_grid(screenshot_path, grid_image_path)
            if rows <= 0 or cols <= 0 or not os.path.exists(grid_image_path):
                log_with_color(f"ERROR: Failed to create grid image at {grid_image_path}", "red", level="error")
                log_with_color("Skipping this round and continuing...", "yellow", level="warning")
                _safe_remove(screenshot_path)
                _safe_remove(xml_path)
                _safe_remove(grid_image_path)
                time.sleep(configs["REQUEST_INTERVAL"])
                continue
            image = grid_image_path
            prompt = prompts.task_template_grid
        else:
            clickable_list = []
            focusable_list = []
            traverse_tree(xml_path, clickable_list, "clickable", True)
            traverse_tree(xml_path, focusable_list, "focusable", True)
            elem_list = clickable_list.copy()
            for elem in focusable_list:
                bbox = elem.bbox
                center = (bbox[0][0] + bbox[1][0]) // 2, (bbox[0][1] + bbox[1][1]) // 2
                close = False
                for e in clickable_list:
                    bbox = e.bbox
                    center_ = (bbox[0][0] + bbox[1][0]) // 2, (bbox[0][1] + bbox[1][1]) // 2
                    dist = (abs(center[0] - center_[0]) ** 2 + abs(center[1] - center_[1]) ** 2) ** 0.5
                    if dist <= configs["MIN_DIST"]:
                        close = True
                        break
                if not close:
                    elem_list.append(elem)
            labeled_image_path = os.path.join(task_dir, f"{dir_name}_{round_count}_labeled.png")
            draw_result = draw_bbox_multi(
                screenshot_path,
                labeled_image_path,
                elem_list,
                dark_mode=configs["DARK_MODE"],
            )
            if draw_result is None or not os.path.exists(labeled_image_path):
                log_with_color(f"ERROR: Failed to create labeled image at {labeled_image_path}", "red", level="error")
                log_with_color("Switching to grid mode for next round...", "yellow", level="warning")
                grid_on = True
                _safe_remove(screenshot_path)
                _safe_remove(xml_path)
                _safe_remove(labeled_image_path)
                time.sleep(configs["REQUEST_INTERVAL"])
                continue
            image = labeled_image_path
            if no_doc:
                prompt = re.sub(r"<ui_document>", "", prompts.task_template)
            else:
                ui_doc = ""
                for i, elem in enumerate(elem_list):
                    doc_path = os.path.join(docs_dir, f"{elem.uid}.txt")
                    if not os.path.exists(doc_path):
                        continue
                    ui_doc += f"Documentation of UI element labeled with the numeric tag '{i + 1}':\n"
                    doc_content = ast.literal_eval(open(doc_path, "r").read())
                    if doc_content["tap"]:
                        ui_doc += f"This UI element is clickable. {doc_content['tap']}\n\n"
                    if doc_content["text"]:
                        ui_doc += f"This UI element can receive text input. The text input is used for the following " \
                                f"purposes: {doc_content['text']}\n\n"
                    if doc_content["long_press"]:
                        ui_doc += f"This UI element is long clickable. {doc_content['long_press']}\n\n"
                    if doc_content["v_swipe"]:
                        ui_doc += f"This element can be swiped directly without tapping. You can swipe vertically on " \
                                f"this UI element. {doc_content['v_swipe']}\n\n"
                    if doc_content["h_swipe"]:
                        ui_doc += f"This element can be swiped directly without tapping. You can swipe horizontally on " \
                                f"this UI element. {doc_content['h_swipe']}\n\n"
                log_with_color(f"Documentations retrieved for the current interface:\n{ui_doc}", "magenta", level="info")
                ui_doc = """
                You also have access to the following documentations that describes the functionalities of UI 
                elements you can interact on the screen. These docs are crucial for you to determine the target of your 
                next action. You should always prioritize these documented elements for interaction:""" + ui_doc
                prompt = re.sub(r"<ui_document>", ui_doc, prompts.task_template)
        prompt = re.sub(r"<task_description>", task_desc, prompt)
        prompt = re.sub(r"<last_act>", last_act, prompt)
        try:
            la = str(last_act) if last_act is not None else ""
        except Exception:
            la = ""
        if la:
            if len(la) > 800:
                la = la[:800] + "\n...[truncated]"
            log_with_color(f"<last_act>\n{la}", "cyan", level="info")
        if debug_enabled:
            log_with_color("Thinking about what to do in the next step...", "yellow", level="info")

        # log_with_color(prompt, "green", level="info")

        if stop_event is not None:
            try:
                if stop_event.is_set():
                    stop_reason = "stopped"
                    _safe_remove(screenshot_path)
                    _safe_remove(xml_path)
                    _safe_remove(labeled_image_path)
                    _safe_remove(grid_image_path)
                    break
            except Exception:
                pass

        llm_t0 = time.monotonic()
        status, rsp = mllm.get_model_response(prompt, [image])
        llm_dt = time.monotonic() - llm_t0
        try:
            log_with_color(f"LLM latency: {llm_dt:.2f}s", "yellow", level="info")
        except Exception:
            pass

        if status:
            _emit_model_rsp(round_count, rsp)
            if save_task_log:
                with open(log_path, "a") as logfile:
                    img_name = os.path.basename(str(image)) if image else ""
                    log_item = {"step": round_count, "prompt": prompt, "image": img_name, "response": rsp}
                    logfile.write(json.dumps(log_item) + "\n")
            
            if grid_on:
                res = parse_grid_rsp(rsp)
            else:
                res = parse_explore_rsp(rsp)
            act_name = res[0]
            if act_name == "FINISH":
                task_complete = True
                _safe_remove(screenshot_path)
                _safe_remove(xml_path)
                _safe_remove(labeled_image_path)
                _safe_remove(grid_image_path)
                break
            if act_name == "ERROR":
                _safe_remove(screenshot_path)
                _safe_remove(xml_path)
                _safe_remove(labeled_image_path)
                _safe_remove(grid_image_path)
                break
            last_act = res[-1]
            res = res[:-1]
            if act_name == "tap":
                _, area = res
                try:
                    area = int(area)
                except Exception:
                    area = -1
                if area < 1 or area > len(elem_list):
                    log_with_color(f"ERROR: invalid element index {area} (elem_count={len(elem_list)})", "red", level="error")
                    grid_on = True
                    _safe_remove(screenshot_path)
                    _safe_remove(xml_path)
                    _safe_remove(labeled_image_path)
                    _safe_remove(grid_image_path)
                    time.sleep(configs["REQUEST_INTERVAL"])
                    continue
                tl, br = elem_list[area - 1].bbox
                x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
                ret = controller.tap(x, y)
                if ret == "ERROR":
                    log_with_color("ERROR: tap execution failed", "red", level="error")
                    break
            elif act_name == "text":
                _, input_str = res
                ret = controller.text(input_str)
                if ret == "ERROR":
                    log_with_color("ERROR: text execution failed", "red", level="error")
                    break
            elif act_name == "long_press":
                _, area = res
                try:
                    area = int(area)
                except Exception:
                    area = -1
                if area < 1 or area > len(elem_list):
                    log_with_color(f"ERROR: invalid element index {area} (elem_count={len(elem_list)})", "red", level="error")
                    grid_on = True
                    _safe_remove(screenshot_path)
                    _safe_remove(xml_path)
                    _safe_remove(labeled_image_path)
                    _safe_remove(grid_image_path)
                    time.sleep(configs["REQUEST_INTERVAL"])
                    continue
                tl, br = elem_list[area - 1].bbox
                x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
                ret = controller.long_press(x, y)
                if ret == "ERROR":
                    log_with_color("ERROR: long press execution failed", "red", level="error")
                    break
            elif act_name == "swipe":
                _, area, swipe_dir, dist = res
                try:
                    area = int(area)
                except Exception:
                    area = -1
                if area < 1 or area > len(elem_list):
                    log_with_color(f"ERROR: invalid element index {area} (elem_count={len(elem_list)})", "red", level="error")
                    grid_on = True
                    _safe_remove(screenshot_path)
                    _safe_remove(xml_path)
                    _safe_remove(labeled_image_path)
                    _safe_remove(grid_image_path)
                    time.sleep(configs["REQUEST_INTERVAL"])
                    continue
                tl, br = elem_list[area - 1].bbox
                x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
                ret = controller.swipe(x, y, swipe_dir, dist)
                if ret == "ERROR":
                    log_with_color("ERROR: swipe execution failed", "red", level="error")
                    break
            elif act_name == "grid":
                grid_on = True
            elif act_name == "tap_grid" or act_name == "long_press_grid":
                _, area, subarea = res
                x, y = area_to_xy(area, subarea, width, height, rows, cols)
                if act_name == "tap_grid":
                    ret = controller.tap(x, y)
                    if ret == "ERROR":
                        log_with_color("ERROR: tap execution failed", "red", level="error")
                        break
                else:
                    ret = controller.long_press(x, y)
                    if ret == "ERROR":
                        log_with_color("ERROR: tap execution failed", "red", level="error")
                        break
            elif act_name == "swipe_grid":
                _, start_area, start_subarea, end_area, end_subarea = res
                start_x, start_y = area_to_xy(start_area, start_subarea, width, height, rows, cols)
                end_x, end_y = area_to_xy(end_area, end_subarea, width, height, rows, cols)
                ret = controller.swipe_precise((start_x, start_y), (end_x, end_y))
                if ret == "ERROR":
                    log_with_color("ERROR: tap execution failed", "red", level="error")
                    break
            if act_name != "grid":
                grid_on = False
            _safe_remove(screenshot_path)
            _safe_remove(xml_path)
            # _safe_remove(labeled_image_path)
            _safe_remove(grid_image_path)
            time.sleep(configs["REQUEST_INTERVAL"])
        else:
            log_with_color(rsp, "red", level="error")
            _safe_remove(screenshot_path)
            _safe_remove(xml_path)
            _safe_remove(labeled_image_path)
            _safe_remove(grid_image_path)
            break

    if not task_complete and stop_reason is None:
        if round_count >= configs["MAX_ROUNDS"]:
            stop_reason = "max_rounds"
        else:
            stop_reason = "failure"

    if task_complete:
        log_with_color("Task completed successfully", "yellow", level="info")
    elif stop_reason == "max_rounds":
        log_with_color("Task finished due to reaching max rounds", "yellow", level="warning")
    elif stop_reason == "capture_failed":
        log_with_color("Task finished due to screen capture failures", "red", level="error")
    else:
        log_with_color("Task finished unexpectedly", "red", level="error")
    
    try:
        controller.back()
    except Exception:
        pass
    if not save_task_log:
        _safe_remove(log_path)
        try:
            if os.path.isdir(task_dir) and not os.listdir(task_dir):
                os.rmdir(task_dir)
        except Exception:
            pass
    ret = {
        "ok": True if stop_reason != "stopped" else False,
        "completed": bool(task_complete),
        "rounds": int(round_count),
        "task_dir": str(task_dir),
        "log_path": str(log_path),
        "stop_reason": str(stop_reason) if stop_reason is not None else None,
    }
    return ret
