import os
import sys
import yaml


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


def _yaml_safe_load_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_placeholder_cfg(cfg):
    try:
        model = (cfg.get("MODEL") or "").strip()
        if model == "OpenAI":
            api_key = (cfg.get("OPENAI_API_KEY") or "").strip()
            return (not api_key) or (api_key.lower() == "your_api_key_here")
        if model == "Qwen":
            api_key = (cfg.get("DASHSCOPE_API_KEY") or "").strip()
            return not api_key
        if model == "Doubao":
            api_key = (cfg.get("ARK_API_KEY") or "").strip()
            return not api_key
    except Exception:
        return True
    return False


def _has_real_key_cfg(cfg):
    try:
        model = (cfg.get("MODEL") or "").strip()
        if model == "OpenAI":
            api_key = (cfg.get("OPENAI_API_KEY") or "").strip()
            return bool(api_key) and (api_key.lower() != "your_api_key_here")
        if model == "Qwen":
            api_key = (cfg.get("DASHSCOPE_API_KEY") or "").strip()
            return bool(api_key)
        if model == "Doubao":
            api_key = (cfg.get("ARK_API_KEY") or "").strip()
            return bool(api_key)
    except Exception:
        return False
    return False


def _maybe_refresh_seed_config(src_path, dst_paths):
    if not src_path or not os.path.exists(src_path):
        return
    src_cfg = _yaml_safe_load_file(src_path)
    if not _has_real_key_cfg(src_cfg):
        return

    for dst_path in dst_paths:
        if not dst_path:
            continue
        try:
            dst_exists = os.path.exists(dst_path)
        except Exception:
            dst_exists = False

        should_write = not dst_exists
        if dst_exists:
            dst_cfg = _yaml_safe_load_file(dst_path)
            if _is_placeholder_cfg(dst_cfg) and _has_real_key_cfg(src_cfg):
                should_write = True

        if not should_write:
            continue

        try:
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        except Exception:
            pass

        try:
            with open(src_path, "rb") as rf:
                content = rf.read()
            with open(dst_path, "wb") as wf:
                wf.write(content)
        except Exception:
            pass


def load_config():
    # PyInstaller打包后的临时目录
    if getattr(sys, 'frozen', False):
        # 打包后的环境
        base_path = sys._MEIPASS
        config_path = os.path.join(base_path, 'config.yaml')
    else:
        app_agent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        candidate_paths = []
        env_path = (os.environ.get("APPAGENT_CONFIG_PATH") or "").strip()
        if env_path:
            candidate_paths.append(env_path)

        android_private = (os.environ.get("ANDROID_PRIVATE") or "").strip()
        android_external = _get_android_external_files_dir()
        if android_external:
            candidate_paths.append(os.path.join(android_external, "config.yml"))
            candidate_paths.append(os.path.join(android_external, "config.yaml"))
        candidate_paths.append(os.path.join("/storage/emulated/0", "AppAgent", "config.yml"))
        candidate_paths.append(os.path.join("/storage/emulated/0", "AppAgent", "config.yaml"))
        candidate_paths.append(os.path.join("/sdcard", "AppAgent", "config.yml"))
        candidate_paths.append(os.path.join("/sdcard", "AppAgent", "config.yaml"))
        if android_private:
            candidate_paths.append(os.path.join(android_private, "config.yml"))
            candidate_paths.append(os.path.join(android_private, "config.yaml"))

        candidate_paths.append(os.path.join(app_agent_dir, "config.yml"))
        candidate_paths.append(os.path.join(app_agent_dir, "config.yaml"))

        config_path = None
        for p in candidate_paths:
            try:
                if p and os.path.exists(p):
                    config_path = p
                    break
            except Exception:
                continue

        if config_path is None:
            config_path = os.path.join(app_agent_dir, "config.yaml")

        seed_candidates = [
            os.path.join(app_agent_dir, "config.yml"),
            os.path.join(app_agent_dir, "config.yaml"),
        ]
        seed_config_path = None
        for p in seed_candidates:
            try:
                if os.path.exists(p):
                    seed_config_path = p
                    break
            except Exception:
                continue

        if android_private:
            try:
                dst_yaml = os.path.join(android_private, "config.yaml")
                dst_yml = os.path.join(android_private, "config.yml")
                _maybe_refresh_seed_config(seed_config_path or config_path, [dst_yaml, dst_yml])
            except Exception:
                pass

        if android_external:
            try:
                dst_yaml = os.path.join(android_external, "config.yaml")
                dst_yml = os.path.join(android_external, "config.yml")
                _maybe_refresh_seed_config(seed_config_path or config_path, [dst_yaml, dst_yml])
            except Exception:
                pass
    
    configs = dict(os.environ)
    with open(config_path, "r") as file:
        yaml_data = yaml.safe_load(file)
    configs.update(yaml_data)
    configs["_CONFIG_PATH"] = config_path
    return configs
