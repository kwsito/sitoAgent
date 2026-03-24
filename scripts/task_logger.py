import os
import re
import time
import json
import logging
from datetime import datetime

order_logger = None
order_log_file = None


def setup_order_logging():
    global order_logger, order_log_file

    if order_logger is not None:
        return order_logger

    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(project_root, "logs")
        os.makedirs(log_dir, exist_ok=True)

        log_filename = os.path.join(log_dir, f"task_runtime_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")
        order_log_file = log_filename

        order_logger = logging.getLogger("task_runtime_logger")
        order_logger.setLevel(logging.INFO)

        if order_logger.handlers:
            order_logger.handlers.clear()

        file_handler = logging.FileHandler(log_filename, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(message)s")
        file_handler.setFormatter(formatter)
        order_logger.addHandler(file_handler)

        return order_logger
    except Exception as e:
        print(f"[error] setup task logger failed: {e}")
        return None


def log_to_order(message):
    global order_logger

    try:
        if order_logger is None:
            setup_order_logging()

        if order_logger:
            order_logger.info(str(message))
    except Exception as e:
        print(f"[error] log_to_order failed: {e}")


def parse_log_content(log_text):
    observation = ""
    thought = ""
    action = ""
    summary = ""

    if not log_text:
        return observation, thought, action, summary

    log_text = str(log_text).replace("<br/>", "\n").replace("<br>", "\n")

    obs_match = re.search(r"Observation:\s*(.*?)(?=\s*(?:Thought:|Action:|Summary:)|$)", log_text, re.DOTALL)
    if obs_match:
        observation = obs_match.group(1).strip()

    thought_match = re.search(r"Thought:\s*(.*?)(?=\s*(?:Observation:|Action:|Summary:)|$)", log_text, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    action_match = re.search(r"Action:\s*(.*?)(?=\s*(?:Observation:|Thought:|Summary:)|$)", log_text, re.DOTALL)
    if action_match:
        action = action_match.group(1).strip()

    summary_match = re.search(r"Summary:\s*(.*?)(?=\s*(?:Observation:|Thought:|Action:)|$)", log_text, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()

    return observation, thought, action, summary


def log_task_step(log_text, running=True):
    try:
        observation, thought, action, summary = parse_log_content(log_text)
        payload = {
            "observation": observation,
            "thought": thought,
            "action": action,
            "summary": summary,
            "running": bool(running),
            "ts_ms": int(time.time() * 1000),
        }
        log_to_order("[task_step] " + json.dumps(payload, ensure_ascii=False))
        return True
    except Exception as e:
        log_to_order(f"[task_step] failed: {e}")
        return False


def log_task_complete(summary="任务已完成"):
    try:
        payload = {"summary": str(summary), "running": False, "ts_ms": int(time.time() * 1000)}
        log_to_order("[task_complete] " + json.dumps(payload, ensure_ascii=False))
        return True
    except Exception:
        return False


def log_task_error(error_message, error_type="failure"):
    try:
        payload = {
            "error_type": str(error_type),
            "error_message": str(error_message),
            "running": False,
            "ts_ms": int(time.time() * 1000),
        }
        log_to_order("[task_error] " + json.dumps(payload, ensure_ascii=False))
        return True
    except Exception:
        return False

