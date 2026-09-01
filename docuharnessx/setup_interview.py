"""Interactive setup interview: credentials then (later) ontology proposals.

Task 2.4 owns the credential prompts: DeepSeek Enter defaults, ``***`` mask
and keep-existing, and writes only to ``<project>/.env``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, TextIO

__all__ = [
    "API_KEY_MASK",
    "DEEPSEEK_DEFAULT_BASE_URL",
    "DEEPSEEK_DEFAULT_MODEL_ID",
    "CredentialAnswers",
    "load_project_env",
    "prompt_credentials",
    "write_project_env",
]

DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL_ID = "deepseek-v4-flash"
API_KEY_MASK = "***"

_KEY_NAME = "OPENAI_API_KEY"
_BASE_NAME = "OPENAI_API_BASE"
_MODEL_NAME = "OPENAI_DEFAULT_MAIN_MODEL"


@dataclass(frozen=True)
class CredentialAnswers:
    """Accepted credential interview values. ``api_key`` is None when unset."""

    api_key: str | None
    api_base: str
    model_id: str


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'").strip('"')
    return values


def _existing_api_key(project_dir: str, environ: Mapping[str, str]) -> str | None:
    env_key = environ.get(_KEY_NAME)
    if env_key:
        return env_key
    file_key = _parse_env_file(Path(project_dir) / ".env").get(_KEY_NAME)
    return file_key or None


def prompt_credentials(
    project_dir: str,
    *,
    input_fn: Any,
    out: TextIO,
    environ: Mapping[str, str] | None = None,
) -> CredentialAnswers:
    """Ask for API key, base URL, and model. Never print the raw secret."""
    env = dict(os.environ if environ is None else environ)
    existing = _existing_api_key(project_dir, env)

    if existing:
        raw_key = input_fn(f"API key [{API_KEY_MASK}]: ").strip()
        if raw_key in ("", API_KEY_MASK):
            api_key: str | None = existing
        else:
            api_key = raw_key
    else:
        raw_key = input_fn("API key: ").strip()
        api_key = raw_key or None

    raw_base = input_fn(f"Base URL [{DEEPSEEK_DEFAULT_BASE_URL}]: ").strip()
    api_base = raw_base or DEEPSEEK_DEFAULT_BASE_URL

    raw_model = input_fn(f"Model [{DEEPSEEK_DEFAULT_MODEL_ID}]: ").strip()
    model_id = raw_model or DEEPSEEK_DEFAULT_MODEL_ID
    _ = out  # reserved for later ontology-proposal display

    return CredentialAnswers(api_key=api_key, api_base=api_base, model_id=model_id)


def write_project_env(project_dir: str, answers: CredentialAnswers) -> str:
    """Write accepted credentials to ``<project>/.env``. Returns the path."""
    path = Path(project_dir) / ".env"
    current = _parse_env_file(path)
    current[_BASE_NAME] = answers.api_base
    current[_MODEL_NAME] = answers.model_id
    if answers.api_key:
        current[_KEY_NAME] = answers.api_key
    else:
        current.pop(_KEY_NAME, None)

    lines = [
        "# Written by dhx init. Do not commit this file.",
        f"{_BASE_NAME}={current[_BASE_NAME]}",
        f"{_MODEL_NAME}={current[_MODEL_NAME]}",
    ]
    if _KEY_NAME in current:
        lines.append(f"{_KEY_NAME}={current[_KEY_NAME]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def load_project_env(project_dir: str) -> None:
    """Load ``<project>/.env`` into ``os.environ`` without overriding live vars."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    env_path = Path(project_dir) / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)
