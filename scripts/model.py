import re
import os
import logging
from datetime import datetime
from abc import abstractmethod
from typing import List
from http import HTTPStatus

import requests
try:
    import dashscope
except Exception:
    dashscope = None

try:
    from utils import print_with_color, encode_image
except Exception:
    from scripts.utils import print_with_color, encode_image

# 设置model日志记录器
_model_logger = None
_model_log_file = None
_save_model_log = (os.environ.get("ORDERQUERY_SAVE_MODEL_LOG") or "").strip() == "1"
_model_debug = (os.environ.get("ORDERQUERY_MODEL_DEBUG") or "").strip() == "1"

def setup_model_logging():
    """配置model日志记录器"""
    global _model_logger, _model_log_file
    
    if _model_logger is not None:
        return _model_logger

    if not _save_model_log:
        return None
    
    try:
        # 创建logs目录（如果不存在）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(project_root, 'logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 生成带日期时间的日志文件名
        log_filename = os.path.join(log_dir, f"model_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")
        _model_log_file = log_filename
        
        # 创建logger
        _model_logger = logging.getLogger('model_logger')
        _model_logger.setLevel(logging.INFO)
        
        # 避免重复添加handler
        if _model_logger.handlers:
            _model_logger.handlers.clear()
        
        # 创建文件handler
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # 定义日志格式
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # 添加handler到logger
        _model_logger.addHandler(file_handler)
        
        return _model_logger
    except Exception as e:
        print(f"[错误] 初始化model日志记录器失败: {e}")
        return None

def log_print_with_color(text: str, color=""):
    """打印带颜色的文本，同时记录到日志文件"""
    if color == "red" or _model_debug:
        print_with_color(text, color)
    
    # 然后记录到日志
    try:
        if (_model_logger is None) and _save_model_log:
            setup_model_logging()
        
        if _model_logger:
            # 添加颜色标识到日志中
            color_prefix = f"[{color.upper()}] " if color else ""
            _model_logger.info(f"{color_prefix}{text}")
    except Exception as e:
        print(f"[错误] 记录到model日志失败: {e}")



class BaseModel:
    def __init__(self):
        pass

    @abstractmethod
    def get_model_response(self, prompt: str, images: List[str]) -> (bool, str):
        pass


class OpenAIModel(BaseModel):
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float, max_tokens: int):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def get_model_response(self, prompt: str, images: List[str]) -> (bool, str):
        max_retries = 2  # 最多重试2次
        for attempt in range(max_retries + 1):
            try:
                content = [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
                for img in images:
                    base64_img = encode_image(img)
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_img}"
                        }
                    })
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens
                }
                resp = requests.post(self.base_url, headers=headers, json=payload, timeout=90)
                if not (200 <= int(resp.status_code) < 300):
                    body = (resp.text or "").strip()
                    body_snippet = re.sub(r"\s+", " ", body)[:800]
                    err_msg = f"ERROR: Model HTTP {resp.status_code} (attempt {attempt + 1}/{max_retries + 1}): {body_snippet or '<empty body>'}"
                    log_print_with_color(err_msg, "red")
                    if attempt < max_retries:
                        continue
                    return False, err_msg

                try:
                    response = resp.json()
                except Exception as e:
                    body = (resp.text or "").strip()
                    body_snippet = re.sub(r"\s+", " ", body)[:800]
                    err_msg = f"ERROR: Model response JSON parse failed (attempt {attempt + 1}/{max_retries + 1}): {e}; body={body_snippet or '<empty body>'}"
                    log_print_with_color(err_msg, "red")
                    if attempt < max_retries:
                        continue
                    return False, err_msg
                if "error" in response:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API returned error (attempt {attempt + 1}/{max_retries + 1}): {response['error']['message']}", "red")
                        continue
                    return False, response["error"]["message"]
                
                # 检查响应结构
                if "choices" not in response or len(response["choices"]) == 0:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API returned empty choices (attempt {attempt + 1}/{max_retries + 1})", "red")
                        continue
                    return False, "API returned empty choices"
                
                if "message" not in response["choices"][0]:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API response missing message field (attempt {attempt + 1}/{max_retries + 1})", "red")
                        continue
                    return False, "API response missing message field"
                
                if "content" not in response["choices"][0]["message"]:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API response missing content field (attempt {attempt + 1}/{max_retries + 1})", "red")
                        continue
                    return False, "API response missing content field"
                
                content_response = response["choices"][0]["message"]["content"]
                
                # 检查内容是否为空或仅包含空白字符
                if not content_response or content_response.strip() == "":
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: Model returned empty response (attempt {attempt + 1}/{max_retries + 1})", "red")
                        continue
                    return False, "Model returned empty response"
                
                # 显示费用信息
                if "usage" in response:
                    usage = response["usage"]
                    prompt_tokens = usage["prompt_tokens"]
                    completion_tokens = usage["completion_tokens"]
                    log_print_with_color(f"Request cost is "
                                   f"${'{0:.2f}'.format(prompt_tokens / 1000 * 0.01 + completion_tokens / 1000 * 0.03)}",
                                   "yellow")
                
                return True, content_response
            except Exception as e:
                if attempt < max_retries:
                    log_print_with_color(f"ERROR: Exception occurred (attempt {attempt + 1}/{max_retries + 1}): {str(e)}", "red")
                    continue
                return False, f"Exception in get_model_response: {str(e)}"
        
        return False, "Max retries exceeded"


class DoubaoModel(BaseModel):
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float, top_p: float, max_tokens: int, reasoning_effort: str):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        try:
            self.temperature = float(temperature)
        except Exception:
            self.temperature = 1.0
        try:
            self.top_p = float(top_p)
        except Exception:
            self.top_p = 0.7
        try:
            self.max_tokens = int(max_tokens)
        except Exception:
            self.max_tokens = 4096
        if self.max_tokens <= 0:
            self.max_tokens = 4096
        if self.max_tokens > 8192:
            self.max_tokens = 8192
        self.reasoning_effort = reasoning_effort or ""

    def get_model_response(self, prompt: str, images: List[str]) -> (bool, str):
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                content = [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
                for img in images:
                    base64_img = encode_image(img)
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_img}"
                        }
                    })
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "max_tokens": self.max_tokens
                }
                if self.reasoning_effort:
                    payload["reasoning_effort"] = self.reasoning_effort
                resp = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
                if not (200 <= int(resp.status_code) < 300):
                    body = (resp.text or "").strip()
                    body_snippet = re.sub(r"\s+", " ", body)[:800]
                    err_msg = f"ERROR: Model HTTP {resp.status_code} (attempt {attempt + 1}/{max_retries + 1}): {body_snippet or '<empty body>'}"
                    log_print_with_color(err_msg, "red")
                    if attempt < max_retries:
                        continue
                    return False, err_msg

                try:
                    response = resp.json()
                except Exception as e:
                    body = (resp.text or "").strip()
                    body_snippet = re.sub(r"\s+", " ", body)[:800]
                    err_msg = f"ERROR: Model response JSON parse failed (attempt {attempt + 1}/{max_retries + 1}): {e}; body={body_snippet or '<empty body>'}"
                    log_print_with_color(err_msg, "red")
                    if attempt < max_retries:
                        continue
                    return False, err_msg
                if "error" in response:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API returned error (attempt {attempt + 1}/{max_retries + 1}): {response['error'].get('message', '')}", "red")
                        continue
                    return False, response["error"].get("message", "")

                if "choices" not in response or len(response["choices"]) == 0:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API returned empty choices (attempt {attempt + 1}/{max_retries + 1})", "red")
                        continue
                    return False, "API returned empty choices"

                if "message" not in response["choices"][0]:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API response missing message field (attempt {attempt + 1}/{max_retries + 1})", "red")
                        continue
                    return False, "API response missing message field"

                if "content" not in response["choices"][0]["message"]:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API response missing content field (attempt {attempt + 1}/{max_retries + 1})", "red")
                        continue
                    return False, "API response missing content field"

                content_response = response["choices"][0]["message"]["content"]
                if isinstance(content_response, list):
                    texts = []
                    for part in content_response:
                        if isinstance(part, dict) and part.get("text"):
                            texts.append(part["text"])
                    content_response = "\n".join(texts).strip()
                if not content_response or str(content_response).strip() == "":
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: Model returned empty response (attempt {attempt + 1}/{max_retries + 1})", "red")
                        continue
                    return False, "Model returned empty response"

                return True, content_response
            except Exception as e:
                if attempt < max_retries:
                    log_print_with_color(f"ERROR: Exception occurred (attempt {attempt + 1}/{max_retries + 1}): {str(e)}", "red")
                    continue
                return False, f"Exception in get_model_response: {str(e)}"

        return False, "Max retries exceeded"


class QwenModel(BaseModel):
    def __init__(self, api_key: str, model: str):
        super().__init__()
        self.model = model
        if dashscope is None:
            raise ImportError("dashscope is required for QwenModel but is not installed")
        dashscope.api_key = api_key

    def get_model_response(self, prompt: str, images: List[str]) -> (bool, str):
        max_retries = 2  # 最多重试2次
        for attempt in range(max_retries + 1):
            try:
                content = [{
                    "text": prompt
                }]
                for img in images:
                    img_path = f"file://{img}"
                    content.append({
                        "image": img_path
                    })
                messages = [
                    {
                        "role": "user",
                        "content": content
                    }
                ]
                response = dashscope.MultiModalConversation.call(model=self.model, messages=messages)
                if response.status_code != HTTPStatus.OK:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API returned error (attempt {attempt + 1}/{max_retries + 1}): {response.message}", "yellow")
                        continue
                    return False, response.message
                
                # 检查响应结构
                if not hasattr(response.output, 'choices') or len(response.output.choices) == 0:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API returned empty choices (attempt {attempt + 1}/{max_retries + 1})", "yellow")
                        continue
                    return False, "API returned empty choices"
                
                if not hasattr(response.output.choices[0].message, 'content') or len(response.output.choices[0].message.content) == 0:
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: API response missing content (attempt {attempt + 1}/{max_retries + 1})", "yellow")
                        continue
                    return False, "API response missing content"
                
                content_response = response.output.choices[0].message.content[0]["text"]
                
                # 检查内容是否为空或仅包含空白字符
                if not content_response or content_response.strip() == "":
                    if attempt < max_retries:
                        log_print_with_color(f"ERROR: Model returned empty response (attempt {attempt + 1}/{max_retries + 1})", "yellow")
                        continue
                    return False, "Model returned empty response"
                
                return True, content_response
            except Exception as e:
                if attempt < max_retries:
                    log_print_with_color(f"ERROR: Exception occurred (attempt {attempt + 1}/{max_retries + 1}): {str(e)}", "yellow")
                    continue
                return False, f"Exception in get_model_response: {str(e)}"
        
        return False, "Max retries exceeded"


def parse_explore_rsp(rsp):
    try:
        observation_matches = re.findall(r"Observation: (.*?)$", rsp, re.MULTILINE)
        think_matches = re.findall(r"Thought: (.*?)$", rsp, re.MULTILINE)
        act_matches = re.findall(r"Action: (.*?)$", rsp, re.MULTILINE)
        last_act_matches = re.findall(r"Summary: (.*?)$", rsp, re.MULTILINE)
        
        if not observation_matches or not think_matches or not act_matches or not last_act_matches:
            log_print_with_color(f"ERROR: Invalid response format. Required fields missing.", "red")
            log_print_with_color(f"Response content:\n{rsp}", "red")
            return ["ERROR"]
        
        observation = observation_matches[0]
        think = think_matches[0]
        act = act_matches[0]
        last_act = last_act_matches[0]
        log_print_with_color("Observation:", "yellow")
        log_print_with_color(observation, "magenta")
        log_print_with_color("Thought:", "yellow")
        log_print_with_color(think, "magenta")
        log_print_with_color("Action:", "yellow")
        log_print_with_color(act, "magenta")
        log_print_with_color("Summary:", "yellow")
        log_print_with_color(last_act, "magenta")
        if "FINISH" in act:
            return ["FINISH"]
        act_name = act.split("(")[0]
        if act_name == "tap":
            area = int(re.findall(r"tap\((.*?)\)", act)[0])
            return [act_name, area, last_act]
        elif act_name == "text":
            input_str = re.findall(r"text\((.*?)\)", act)[0][1:-1]
            return [act_name, input_str, last_act]
        elif act_name == "long_press":
            area = int(re.findall(r"long_press\((.*?)\)", act)[0])
            return [act_name, area, last_act]
        elif act_name == "swipe":
            params = re.findall(r"swipe\((.*?)\)", act)[0]
            area, swipe_dir, dist = params.split(",")
            area = int(area)
            swipe_dir = swipe_dir.strip()[1:-1]
            dist = dist.strip()[1:-1]
            return [act_name, area, swipe_dir, dist, last_act]
        elif act_name == "grid":
            return [act_name]
        else:
            log_print_with_color(f"ERROR: Undefined act {act_name}!", "red")
            return ["ERROR"]
    except Exception as e:
        log_print_with_color(f"ERROR: an exception occurs while parsing the model response: {e}", "red")
        log_print_with_color(rsp, "red")
        return ["ERROR"]


def parse_grid_rsp(rsp):
    try:
        observation_matches = re.findall(r"Observation: (.*?)$", rsp, re.MULTILINE)
        think_matches = re.findall(r"Thought: (.*?)$", rsp, re.MULTILINE)
        act_matches = re.findall(r"Action: (.*?)$", rsp, re.MULTILINE)
        last_act_matches = re.findall(r"Summary: (.*?)$", rsp, re.MULTILINE)
        
        if not observation_matches or not think_matches or not act_matches or not last_act_matches:
            log_print_with_color(f"ERROR: Invalid response format. Required fields missing.", "red")
            log_print_with_color(f"Response content:\n{rsp}", "red")
            return ["ERROR"]
        
        observation = observation_matches[0]
        think = think_matches[0]
        act = act_matches[0]
        last_act = last_act_matches[0]
        log_print_with_color("Observation:", "yellow")
        log_print_with_color(observation, "magenta")
        log_print_with_color("Thought:", "yellow")
        log_print_with_color(think, "magenta")
        log_print_with_color("Action:", "yellow")
        log_print_with_color(act, "magenta")
        log_print_with_color("Summary:", "yellow")
        log_print_with_color(last_act, "magenta")
        if "FINISH" in act:
            return ["FINISH"]
        act_name = act.split("(")[0]
        if act_name == "tap":
            params = re.findall(r"tap\((.*?)\)", act)[0].split(",")
            area = int(params[0].strip())
            subarea = params[1].strip()[1:-1]
            return [act_name + "_grid", area, subarea, last_act]
        elif act_name == "long_press":
            params = re.findall(r"long_press\((.*?)\)", act)[0].split(",")
            area = int(params[0].strip())
            subarea = params[1].strip()[1:-1]
            return [act_name + "_grid", area, subarea, last_act]
        elif act_name == "swipe":
            params = re.findall(r"swipe\((.*?)\)", act)[0].split(",")
            start_area = int(params[0].strip())
            start_subarea = params[1].strip()[1:-1]
            end_area = int(params[2].strip())
            end_subarea = params[3].strip()[1:-1]
            return [act_name + "_grid", start_area, start_subarea, end_area, end_subarea, last_act]
        elif act_name == "grid":
            return [act_name]
        else:
            log_print_with_color(f"ERROR: Undefined act {act_name}!", "red")
            return ["ERROR"]
    except Exception as e:
        log_print_with_color(f"ERROR: an exception occurs while parsing the model response: {e}", "red")
        log_print_with_color(rsp, "red")
        return ["ERROR"]


def parse_reflect_rsp(rsp):
    try:
        decision_matches = re.findall(r"Decision: (.*?)$", rsp, re.MULTILINE)
        think_matches = re.findall(r"Thought: (.*?)$", rsp, re.MULTILINE)
        
        if not decision_matches or not think_matches:
            log_print_with_color(f"ERROR: Invalid response format. Required fields missing.", "red")
            log_print_with_color(f"Response content:\n{rsp}", "red")
            return ["ERROR"]
        
        decision = decision_matches[0]
        think = think_matches[0]
        log_print_with_color("Decision:", "yellow")
        log_print_with_color(decision, "magenta")
        log_print_with_color("Thought:", "yellow")
        log_print_with_color(think, "magenta")
        if decision == "INEFFECTIVE":
            return [decision, think]
        elif decision == "BACK" or decision == "CONTINUE" or decision == "SUCCESS":
            doc_matches = re.findall(r"Documentation: (.*?)$", rsp, re.MULTILINE)
            if not doc_matches:
                log_print_with_color(f"ERROR: Documentation field missing in response.", "red")
                log_print_with_color(f"Response content:\n{rsp}", "red")
                return ["ERROR"]
            doc = doc_matches[0]
            log_print_with_color("Documentation:", "yellow")
            log_print_with_color(doc, "magenta")
            return [decision, think, doc]
        else:
            log_print_with_color(f"ERROR: Undefined decision {decision}!", "red")
            return ["ERROR"]
    except Exception as e:
        log_print_with_color(f"ERROR: an exception occurs while parsing the model response: {e}", "red")
        log_print_with_color(rsp, "red")
        return ["ERROR"]
