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


def _is_missing_key(api_key):
    value = (api_key or "").strip()
    return (not value) or (value.lower() == "your_api_key_here") or (value == "sk-")


def _is_placeholder_cfg(cfg):
    try:
        model = (cfg.get("MODEL") or "").strip()
        if model == "OpenAI":
            api_key = (cfg.get("OPENAI_API_KEY") or "").strip()
            return _is_missing_key(api_key)
        if model == "Qwen":
            api_key = (cfg.get("DASHSCOPE_API_KEY") or "").strip()
            return _is_missing_key(api_key)
        if model == "Doubao":
            api_key = (cfg.get("ARK_API_KEY") or "").strip()
            return _is_missing_key(api_key)
    except Exception:
        return True
    return False


def _has_real_key_cfg(cfg):
    try:
        model = (cfg.get("MODEL") or "").strip()
        if model == "OpenAI":
            api_key = (cfg.get("OPENAI_API_KEY") or "").strip()
            return not _is_missing_key(api_key)
        if model == "Qwen":
            api_key = (cfg.get("DASHSCOPE_API_KEY") or "").strip()
            return not _is_missing_key(api_key)
        if model == "Doubao":
            api_key = (cfg.get("ARK_API_KEY") or "").strip()
            return not _is_missing_key(api_key)
    except Exception:
        return False
    return False


def _sync_seed_config(src_path, dst_paths):
    if not src_path or not os.path.exists(src_path):
        return

    try:
        with open(src_path, "rb") as rf:
            content = rf.read()
    except Exception:
        return

    for dst_path in dst_paths:
        if not dst_path:
            continue

        try:
            if os.path.abspath(dst_path) == os.path.abspath(src_path):
                continue
        except Exception:
            pass

        try:
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        except Exception:
            pass

        try:
            if os.path.exists(dst_path):
                with open(dst_path, "rb") as rf:
                    if rf.read() == content:
                        continue
        except Exception:
            pass

        try:
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

        env_path = (os.environ.get("APPAGENT_CONFIG_PATH") or "").strip()
        android_private = (os.environ.get("ANDROID_PRIVATE") or "").strip()
        android_external = _get_android_external_files_dir()
        config_path = None
        if env_path:
            try:
                if os.path.exists(env_path):
                    config_path = env_path
            except Exception:
                config_path = None

        if config_path is None and seed_config_path:
            config_path = seed_config_path

        sync_targets = [
            os.path.join("/storage/emulated/0", "AppAgent", "config.yml"),
            os.path.join("/storage/emulated/0", "AppAgent", "config.yaml"),
            os.path.join("/sdcard", "AppAgent", "config.yml"),
            os.path.join("/sdcard", "AppAgent", "config.yaml"),
        ]
        if android_private:
            sync_targets.extend([
                os.path.join(android_private, "config.yml"),
                os.path.join(android_private, "config.yaml"),
            ])
        if android_external:
            sync_targets.extend([
                os.path.join(android_external, "config.yml"),
                os.path.join(android_external, "config.yaml"),
            ])

        if seed_config_path:
            _sync_seed_config(seed_config_path, sync_targets)

        if config_path is None:
            candidate_paths = []
            if android_external:
                candidate_paths.extend([
                    os.path.join(android_external, "config.yml"),
                    os.path.join(android_external, "config.yaml"),
                ])
            candidate_paths.extend([
                os.path.join("/storage/emulated/0", "AppAgent", "config.yml"),
                os.path.join("/storage/emulated/0", "AppAgent", "config.yaml"),
                os.path.join("/sdcard", "AppAgent", "config.yml"),
                os.path.join("/sdcard", "AppAgent", "config.yaml"),
            ])
            if android_private:
                candidate_paths.extend([
                    os.path.join(android_private, "config.yml"),
                    os.path.join(android_private, "config.yaml"),
                ])

            for p in candidate_paths:
                try:
                    if p and os.path.exists(p):
                        config_path = p
                        break
                except Exception:
                    continue

        if config_path is None:
            config_path = os.path.join(app_agent_dir, "config.yaml")
    
    configs = dict(os.environ)
    with open(config_path, "r", encoding="utf-8") as file:
        yaml_data = yaml.safe_load(file) or {}
    configs.update(yaml_data)
    configs["_CONFIG_PATH"] = config_path
    return configs
