"""Library location and settings.

The library lives outside the repo, in ``~/VideoMentor`` unless ``VM_HOME`` says
otherwise. Settings sit beside it in ``config.toml``; a missing file means defaults.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


def library_home() -> Path:
    return Path(os.environ.get("VM_HOME", Path.home() / "VideoMentor")).expanduser()


@dataclass
class Settings:
    # Chrome profile whose YouTube login reads Watch Later.
    watch_later_profile: str = "Default"
    # Chrome profiles scanned for YouTube bookmarks; "*" means every profile.
    bookmark_chrome_profiles: list[str] = field(default_factory=lambda: ["*"])
    bookmark_safari: bool = True
    host: str = "127.0.0.1"
    # Change it if another app on your machine already uses this port.
    port: int = 8791
    # Shared secret a device presents once at /pair.
    pair_code: str = ""
    sync_interval_hours: float = 6.0
    prep_model: str = "haiku"
    analysis_model: str = "sonnet"
    prep_batch_size: int = 20
    enrich_concurrency: int = 3
    # Kept (not prioritized) items are analyzed at most once per this many minutes.
    kept_trickle_minutes: float = 10.0
    # Skills the mentor analysis and signal score judge videos against.
    # A starting point; edit freely (Status > Signal settings).
    skill_map: list[str] = field(
        default_factory=lambda: [
            "Leadership",
            "Sales",
            "Negotiation",
            "Marketing",
            "Communication",
            "Strategy",
            "Finance",
            "AI and tech",
            "Productivity",
        ]
    )
    # What the signal score (1 to 5) rewards: clear learnings you can apply, in any
    # of these areas of life. Editable on the phone (Status > Signal settings).
    signal_areas: list[str] = field(
        default_factory=lambda: [
            "Business and career",
            "Communication and relationships",
            "Health and wellbeing",
            "Personal growth and mindset",
            "Money",
            "Practical skills and tools",
        ]
    )
    signal_guidance: str = (
        "Score how many clear, specific learnings the video offers that I could apply. "
        "Any area of life counts, not only business. A video with one strong, usable idea "
        "beats a long one with vague advice. Entertainment, news, music and opinion with "
        "nothing to apply score low."
    )


def config_path() -> Path:
    return library_home() / "config.toml"


def load_settings() -> Settings:
    path = config_path()
    settings = Settings()
    if path.exists():
        data = tomllib.loads(path.read_text())
        known = {f.name for f in fields(Settings)}
        for key, value in data.items():
            if key in known:
                setattr(settings, key, value)
    if not PAIR_CODE.match(str(settings.pair_code or "")):
        # Missing, or the old 8-character code: devices pair again with the new one.
        settings.pair_code = new_pair_code()
        try:
            save_settings(settings)
        except OSError as e:  # read-only config: keep going with this run's code
            logging.getLogger(__name__).warning("could not save the new pairing code: %s", e)
    return settings


PAIR_CODE = re.compile(r"^\d{4}-\d{4}-\d{4}$")


def new_pair_code() -> str:
    """12 random digits shown as 1234-5678-9012: easy on a phone's number pad, and with
    the pairing lockout (10 tries per 15 minutes) far out of reach of guessing."""
    digits = "".join(secrets.choice("0123456789") for _ in range(12))
    return f"{digits[:4]}-{digits[4:8]}-{digits[8:]}"


def normalize_code(code: str) -> str:
    """Compare codes without spaces or dashes, ignoring case."""
    return re.sub(r"[\s-]", "", code or "").upper()


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def save_settings(settings: Settings) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# VideoMentor settings. See docs/setup.md for what each one does."]
    for f in fields(Settings):
        lines.append(f"{f.name} = {_toml_value(getattr(settings, f.name))}")
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
