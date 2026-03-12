import asyncio
import json
import logging
import os
from typing import Any, Callable, Dict, List
from copy import deepcopy

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class ConfigManager:
    _instance = None
    _config: Dict[str, Any] = {}
    _on_change_callbacks: List[Callable] = []

    # Config file path - mount as ConfigMap volume in Kubernetes
    CONFIG_FILE_PATH = os.getenv("APP_CONFIG_PATH", "/app/config/app_config.json")
    # Optional default config bundled in image; primary config overrides this
    DEFAULT_CONFIG_FILE_PATH = os.getenv(
        "APP_CONFIG_DEFAULT_PATH",
        "/app/app_config.default.json"
    )
    LEGACY_DEFAULT_CONFIG_FILE_PATH = "qubiva_tf_deployment/app_config.json"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    @classmethod
    def register_on_change(cls, callback: Callable):
        """Register a callback to be invoked when config changes.

        Callbacks receive (changed_keys: List[str]) — the top-level keys
        whose values differ from the previous config.
        """
        cls._on_change_callbacks.append(callback)

    @staticmethod
    def _load_config_file(path: str) -> Dict[str, Any]:
        """Load JSON config file and return dict, or empty dict if unavailable."""
        if not path or not os.path.exists(path):
            return {}

        with open(path, 'r') as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Config at {path} must be a JSON object")

        return data

    @staticmethod
    def _deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge override into base and return merged dict."""
        merged = deepcopy(base)
        for key, value in override.items():
            if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(value, dict)
            ):
                merged[key] = ConfigManager._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    async def sync_config(self) -> bool:
        """Load/reload config with default fallback + override semantics.

        Detects changes from the previous config and fires registered
        on_change callbacks with the list of changed top-level keys.
        """
        try:
            config_path = self.CONFIG_FILE_PATH
            default_path = self.DEFAULT_CONFIG_FILE_PATH

            default_config = self._load_config_file(default_path)
            if not default_config:
                # Local/dev fallback path when running from source tree
                default_config = self._load_config_file(self.LEGACY_DEFAULT_CONFIG_FILE_PATH)
            if default_config:
                logger.debug("Default configuration loaded from %s", default_path)

            if not os.path.exists(config_path):
                logger.warning(f"Config file not found at {config_path}")
                config_data = {}
            else:
                config_data = self._load_config_file(config_path)
                logger.debug("Configuration loaded from %s", config_path)

            if default_config and config_data:
                merged_config = self._deep_merge_dicts(default_config, config_data)
            elif config_data:
                merged_config = config_data
            elif default_config:
                merged_config = default_config
            else:
                if not self.__class__._config:
                    raise FileNotFoundError(
                        f"No configuration found at {config_path} or {default_path}"
                    )
                return False

            # Detect which top-level keys changed
            old_config = self.__class__._config
            changed_keys = self._detect_changes(old_config, merged_config)

            self.__class__._config = merged_config

            if changed_keys:
                logger.info("Config reloaded — changed sections: %s", ", ".join(changed_keys))
                await self._fire_on_change(changed_keys)

            return True

        except Exception as e:
            logger.error(f"Error loading config: {str(e)}")
            if not self.__class__._config:
                raise
            return False

    @staticmethod
    def _detect_changes(old: Dict[str, Any], new: Dict[str, Any]) -> List[str]:
        """Return top-level keys whose values differ between old and new config."""
        if not old:
            return []  # First load — not a "change"

        changed = []
        all_keys = set(old.keys()) | set(new.keys())
        for key in sorted(all_keys):
            old_val = old.get(key)
            new_val = new.get(key)
            if old_val != new_val:
                changed.append(key)
        return changed

    async def _fire_on_change(self, changed_keys: List[str]):
        """Invoke all registered on_change callbacks."""
        for callback in self.__class__._on_change_callbacks:
            try:
                result = callback(changed_keys)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("Config change callback failed: %s", e)

    @classmethod
    def get_config(cls, *keys: str) -> Any:
        """Get config value using nested keys"""
        current = cls._config
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current
