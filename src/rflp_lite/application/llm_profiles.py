from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from rflp_lite.domain.errors import AdapterFailure, InvariantViolation


_PROFILE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_PROTOCOL = "openai-chat"
MAX_LLM_TIMEOUT_SECONDS = 900
_KEYRING_SERVICE = "rflp-lite"

PRESETS: dict[str, dict[str, object]] = {
    "deepseek": {
        "label": "DeepSeek",
        "provider": "openai-compatible",
        "kind": "remote",
        "protocol": _PROTOCOL,
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
    },
    "qwen": {
        "label": "通义千问",
        "provider": "openai-compatible",
        "kind": "remote",
        "protocol": _PROTOCOL,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "openai": {
        "label": "OpenAI API",
        "provider": "openai-compatible",
        "kind": "remote",
        "protocol": _PROTOCOL,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "ollama": {
        "label": "Ollama",
        "provider": "ollama",
        "kind": "local",
        "protocol": _PROTOCOL,
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "llama3.2",
        "context_window": 8192,
        "max_output_tokens": 2048,
        "temperature": 0.0,
        "seed": 42,
        "structured_output_mode": "json_schema",
    },
    "lmstudio": {
        "label": "LM Studio",
        "provider": "openai-compatible",
        "kind": "local",
        "protocol": _PROTOCOL,
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "local-model",
    },
    "custom": {
        "label": "自定义服务",
        "provider": "openai-compatible",
        "kind": "remote",
        "protocol": _PROTOCOL,
        "base_url": "",
        "model": "",
    },
}


def default_config_dir() -> Path:
    override = os.getenv("RFLP_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "rflp-lite"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "rflp-lite"
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "rflp-lite"


def _config_payload(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"active_id": None, "profiles": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterFailure("LLM 配置无法读取") from exc
    if not isinstance(value, dict):
        raise AdapterFailure("LLM 配置格式无效")
    profiles = value.get("profiles", [])
    if not isinstance(profiles, list):
        raise AdapterFailure("LLM 配置档案无效")
    return {"active_id": value.get("active_id"), "profiles": profiles}


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, path)


def _keyring():
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    return keyring


def _profile_id(value: object) -> str:
    result = str(value or "").strip()
    if not _PROFILE_ID.fullmatch(result):
        raise InvariantViolation("LLM 档案 ID 只能包含字母、数字、点、下划线和短横线")
    return result


def _base_url(value: object) -> str:
    result = str(value or "").strip().rstrip("/")
    parsed = urlparse(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvariantViolation("LLM Base URL 必须是有效的 HTTP(S) 地址")
    if "?" in result or "#" in result:
        raise InvariantViolation("LLM Base URL 不应包含查询参数或片段")
    return result


def _provider(payload: Mapping[str, object]) -> str:
    value = str(payload.get("provider", "")).strip().casefold()
    if value in {"openai", "openai-compatible", "openai_chat"}:
        return "openai-compatible"
    if value in {"ollama", "ollama-native"}:
        return "ollama"
    base_url = str(payload.get("base_url", "")).casefold()
    if "11434" in base_url or "ollama" in base_url:
        return "ollama"
    return "openai-compatible"


def _optional_int(
    payload: Mapping[str, object],
    names: tuple[str, ...],
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int | None:
    value: object = None
    present = False
    for name in names:
        if name in payload and payload[name] is not None and payload[name] != "":
            value = payload[name]
            present = True
            break
    if not present:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise InvariantViolation(f"{label} 必须是整数") from exc
    if not minimum <= result <= maximum:
        raise InvariantViolation(f"{label}范围必须是 {minimum} 到 {maximum}")
    return result


def _optional_float(
    payload: Mapping[str, object],
    name: str,
    *,
    minimum: float,
    maximum: float,
    label: str,
) -> float:
    value = payload.get(name, 0.0)
    if value is None or value == "":
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvariantViolation(f"{label} 必须是数字") from exc
    if not minimum <= result <= maximum:
        raise InvariantViolation(f"{label}范围必须是 {minimum} 到 {maximum}")
    return result


def normalize_profile(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise InvariantViolation("LLM 档案必须是对象")
    profile_id = _profile_id(payload.get("id") or payload.get("profile_id"))
    label = str(payload.get("label") or profile_id).strip()
    if not label:
        raise InvariantViolation("LLM 档案名称不能为空")
    kind = str(payload.get("kind", "remote")).strip().lower()
    if kind not in {"local", "remote"}:
        raise InvariantViolation("LLM 档案类型必须是 local 或 remote")
    model_location = str(
        payload.get("model_location", "local" if kind == "local" else "remote")
    ).strip().lower()
    if model_location not in {"local", "remote"}:
        raise InvariantViolation("LLM 模型位置必须是 local 或 remote")
    protocol = str(payload.get("protocol", _PROTOCOL)).strip().lower()
    if protocol != _PROTOCOL:
        raise InvariantViolation("当前只支持 OpenAI-compatible Chat 协议")
    model = str(payload.get("model", "")).strip()
    if not model:
        raise InvariantViolation("LLM 模型名不能为空")
    try:
        timeout = int(payload.get("timeout_seconds", 300))
    except (TypeError, ValueError) as exc:
        raise InvariantViolation("LLM 超时必须是整数") from exc
    if not 1 <= timeout <= MAX_LLM_TIMEOUT_SECONDS:
        raise InvariantViolation(
            f"LLM 超时范围必须是 1 到 {MAX_LLM_TIMEOUT_SECONDS} 秒"
        )
    context_window = _optional_int(
        payload, ("context_window", "local_context_tokens"),
        minimum=512, maximum=1_000_000, label="LLM context window",
    )
    max_output_tokens = _optional_int(
        payload, ("max_output_tokens", "local_max_tokens"),
        minimum=1, maximum=1_000_000, label="LLM max output tokens",
    )
    seed = _optional_int(payload, ("seed",), minimum=0, maximum=2**63 - 1, label="LLM seed")
    temperature = _optional_float(
        payload, "temperature", minimum=0.0, maximum=2.0, label="LLM temperature",
    )
    structured_output_mode = str(payload.get("structured_output_mode", "json_schema")).strip().lower()
    if structured_output_mode not in {"json_schema", "json_object", "json", "none"}:
        raise InvariantViolation("LLM structured output mode 无效")
    reasoning_effort = payload.get("reasoning_effort")
    if reasoning_effort is not None and not isinstance(reasoning_effort, str):
        raise InvariantViolation("LLM reasoning_effort 必须是字符串")
    think = payload.get("think")
    if think is not None and not isinstance(think, bool):
        raise InvariantViolation("LLM think 必须是布尔值")
    chat_template_kwargs = payload.get("chat_template_kwargs")
    if chat_template_kwargs is not None and not isinstance(chat_template_kwargs, Mapping):
        raise InvariantViolation("LLM chat_template_kwargs 必须是对象")
    return {
        "id": profile_id,
        "label": label[:120],
        "provider": _provider(payload),
        "kind": kind,
        "model_location": model_location,
        "protocol": protocol,
        "base_url": _base_url(payload.get("base_url")),
        "model": model[:200],
        "timeout_seconds": timeout,
        "enabled": bool(payload.get("enabled", True)),
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        # Preserve the legacy names consumed by existing local adapters.
        "local_context_tokens": context_window,
        "local_max_tokens": max_output_tokens,
        "temperature": temperature,
        "seed": seed,
        "structured_output_mode": structured_output_mode,
        "reasoning_effort": reasoning_effort.strip() if isinstance(reasoning_effort, str) else None,
        "think": think,
        "chat_template_kwargs": (
            {str(key): value for key, value in chat_template_kwargs.items()}
            if isinstance(chat_template_kwargs, Mapping)
            else None
        ),
    }


class LLMProfileService:
    def __init__(self, config_dir: Path | None = None):
        self.config_dir = (config_dir or default_config_dir()).expanduser().resolve()
        self.path = self.config_dir / "llm-profiles.json"
        self._session_keys: dict[str, str] = {}

    def presets(self) -> dict[str, dict[str, object]]:
        return json.loads(json.dumps(PRESETS, ensure_ascii=False))

    def _read(self) -> dict[str, object]:
        return _config_payload(self.path)

    def _write(self, payload: dict[str, object]) -> None:
        _atomic_write(self.path, payload)

    def _key(self, profile_id: str) -> str | None:
        if profile_id in self._session_keys:
            return self._session_keys[profile_id]
        backend = _keyring()
        if backend is None:
            return None
        try:
            return backend.get_password(_KEYRING_SERVICE, profile_id)
        except Exception:
            return None

    def _save_key(self, profile_id: str, value: str) -> str:
        backend = _keyring()
        if backend is not None:
            try:
                backend.set_password(_KEYRING_SERVICE, profile_id, value)
                self._session_keys.pop(profile_id, None)
                return "system"
            except Exception:
                pass
        self._session_keys[profile_id] = value
        return "session"

    def _delete_key(self, profile_id: str) -> None:
        self._session_keys.pop(profile_id, None)
        backend = _keyring()
        if backend is not None:
            try:
                backend.delete_password(_KEYRING_SERVICE, profile_id)
            except Exception:
                pass

    def _public(self, profile: dict[str, object]) -> dict[str, object]:
        result = dict(profile)
        result["provider"] = _provider(result)
        key = self._key(str(profile["id"]))
        result["api_key_configured"] = bool(key)
        result["credential_storage"] = (
            "system" if key and str(profile["id"]) not in self._session_keys else "session" if key else "none"
        )
        return result

    def snapshot(self) -> dict[str, object]:
        payload = self._read()
        return {
            "active_id": payload.get("active_id"),
            "profiles": [self._public(item) for item in payload["profiles"] if isinstance(item, dict)],
            "config_path": str(self.path),
            "keyring_available": _keyring() is not None,
        }

    def save(self, payload: object) -> dict[str, object]:
        profile = normalize_profile(payload)
        data = self._read()
        profiles = [item for item in data["profiles"] if isinstance(item, dict)]
        existing = next((item for item in profiles if item.get("id") == profile["id"]), None)
        api_key = payload.get("api_key") if isinstance(payload, dict) else None
        if isinstance(api_key, str) and api_key.strip():
            self._save_key(str(profile["id"]), api_key.strip())
        elif existing is None:
            self._delete_key(str(profile["id"]))
        replaced = False
        for index, item in enumerate(profiles):
            if item.get("id") == profile["id"]:
                profiles[index] = profile
                replaced = True
                break
        if not replaced:
            profiles.append(profile)
        active_id = data.get("active_id")
        if bool(payload.get("active", False)) or active_id is None:
            active_id = profile["id"]
        self._write({"active_id": active_id, "profiles": profiles})
        return self._public(profile)

    def activate(self, profile_id: str) -> dict[str, object]:
        profile_id = _profile_id(profile_id)
        data = self._read()
        profile = next((item for item in data["profiles"] if item.get("id") == profile_id), None)
        if not isinstance(profile, dict):
            raise InvariantViolation("LLM 档案不存在")
        data["active_id"] = profile_id
        self._write(data)
        return self._public(profile)

    def delete(self, profile_id: str) -> Mapping[str, object]:
        profile_id = _profile_id(profile_id)
        data = self._read()
        profiles = [item for item in data["profiles"] if item.get("id") != profile_id]
        if len(profiles) == len(data["profiles"]):
            raise InvariantViolation("LLM 档案不存在")
        self._delete_key(profile_id)
        data["profiles"] = profiles
        if data.get("active_id") == profile_id:
            data["active_id"] = profiles[0].get("id") if profiles else None
        self._write(data)
        return {"profile_id": profile_id, "active_id": data.get("active_id")}

    def active_config(self) -> dict[str, object] | None:
        data = self._read()
        profile_id = data.get("active_id")
        profile = next((item for item in data["profiles"] if item.get("id") == profile_id), None)
        if not isinstance(profile, dict):
            return None
        return {**profile, "provider": _provider(profile), "api_key": self._key(str(profile["id"])) or ""}

    def config_for_profile(self, profile_id: str) -> Mapping[str, object]:
        profile_id = _profile_id(profile_id)
        data = self._read()
        profile = next((item for item in data["profiles"] if item.get("id") == profile_id), None)
        if not isinstance(profile, dict):
            raise InvariantViolation("LLM 档案不存在")
        return self.config_for(profile)

    def config_for(self, payload: object) -> dict[str, object]:
        profile = normalize_profile(payload)
        api_key = payload.get("api_key") if isinstance(payload, dict) else ""
        if not isinstance(api_key, str) or not api_key.strip():
            api_key = self._key(str(profile["id"])) or ""
        return {**profile, "api_key": api_key}

    def test(self, payload: object, tester=None) -> dict[str, object]:
        config = self.config_for(payload)
        if config["provider"] == "openai-compatible" and config["kind"] == "remote" and not config["api_key"]:
            raise AdapterFailure("远程 LLM 缺少 API Key")
        if tester is None:
            return {"status": "configured", "profile_id": config["id"]}
        return tester(config)

def environment_config() -> dict[str, object] | None:
    base_url = os.getenv("RFLP_LLM_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("RFLP_LLM_MODEL", "").strip()
    api_key = os.getenv("RFLP_LLM_API_KEY", "").strip()
    if not (base_url and model and api_key):
        return None
    return {
        "id": "environment",
        "label": "环境变量 LLM",
        "kind": "remote",
        "protocol": _PROTOCOL,
        "base_url": base_url,
        "model": model,
        "timeout_seconds": 300,
        "api_key": api_key,
    }
