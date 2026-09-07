"""Model profile settings exposed as a narrow application service."""

from __future__ import annotations

from pathlib import Path

from rflp_lite.application.llm_profiles import LLMProfileService


class SettingsService:
    def __init__(self, config_dir: Path | None = None):
        self.profiles = LLMProfileService(config_dir)

    def list_profiles(self) -> dict[str, object]:
        return self.profiles.snapshot()

    def save_profile(self, payload: object) -> dict[str, object]:
        return self.profiles.save(payload)

    def activate_profile(self, profile_id: str) -> dict[str, object]:
        return self.profiles.activate(profile_id)

    def active_config(self) -> dict[str, object] | None:
        return self.profiles.active_config()
