"""Interactive credential interview (task 2.4, boundary: SetupInterview).

Pins DeepSeek Enter defaults, ``***`` keep-existing, and ``.env`` writes.
No model and no network.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from docuharnessx.setup_interview import (
    API_KEY_MASK,
    DEEPSEEK_DEFAULT_BASE_URL,
    DEEPSEEK_DEFAULT_MODEL_ID,
    prompt_credentials,
    write_project_env,
)


def _scripted(*lines: str):
    answers = iter(lines)
    prompts: list[str] = []

    def _reader(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    _reader.prompts = prompts  # type: ignore[attr-defined]
    return _reader


def test_empty_base_url_and_model_use_deepseek_defaults(tmp_path: Path) -> None:
    out = io.StringIO()
    reader = _scripted("sk-test-key", "", "")
    result = prompt_credentials(
        str(tmp_path),
        input_fn=reader,
        out=out,
        environ={},
    )
    assert result.api_key == "sk-test-key"
    assert result.api_base == DEEPSEEK_DEFAULT_BASE_URL
    assert result.model_id == DEEPSEEK_DEFAULT_MODEL_ID
    prompts = "".join(reader.prompts)  # type: ignore[attr-defined]
    assert DEEPSEEK_DEFAULT_BASE_URL in prompts
    assert DEEPSEEK_DEFAULT_MODEL_ID in prompts
    assert "sk-test-key" not in prompts
    assert "sk-test-key" not in out.getvalue()


def test_existing_key_is_shown_as_mask_not_raw_secret(tmp_path: Path) -> None:
    out = io.StringIO()
    reader = _scripted("", "", "")
    result = prompt_credentials(
        str(tmp_path),
        input_fn=reader,
        out=out,
        environ={"OPENAI_API_KEY": "sk-super-secret-value"},
    )
    prompts = "".join(reader.prompts)  # type: ignore[attr-defined]
    assert API_KEY_MASK in prompts
    assert "sk-super-secret-value" not in prompts
    assert "sk-super-secret-value" not in out.getvalue()
    assert result.api_key == "sk-super-secret-value"


def test_typed_mask_keeps_existing_key(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-from-file\n", encoding="utf-8")
    out = io.StringIO()
    reader = _scripted(API_KEY_MASK, "", "")
    result = prompt_credentials(
        str(tmp_path),
        input_fn=reader,
        out=out,
        environ={},
    )
    assert result.api_key == "sk-from-file"
    prompts = "".join(reader.prompts)  # type: ignore[attr-defined]
    assert "sk-from-file" not in prompts
    assert "sk-from-file" not in out.getvalue()


def test_empty_key_with_none_present_does_not_write_blank_secret(tmp_path: Path) -> None:
    out = io.StringIO()
    result = prompt_credentials(
        str(tmp_path),
        input_fn=_scripted("", "", ""),
        out=out,
        environ={},
    )
    assert result.api_key is None
    path = write_project_env(str(tmp_path), result)
    text = Path(path).read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=" not in text
    assert f"OPENAI_API_BASE={DEEPSEEK_DEFAULT_BASE_URL}" in text
    assert f"OPENAI_DEFAULT_MAIN_MODEL={DEEPSEEK_DEFAULT_MODEL_ID}" in text


def test_write_project_env_is_gitignored(tmp_path: Path) -> None:
    from docuharnessx.setup_interview import CredentialAnswers

    answers = CredentialAnswers(
        api_key="sk-keep",
        api_base=DEEPSEEK_DEFAULT_BASE_URL,
        model_id=DEEPSEEK_DEFAULT_MODEL_ID,
    )
    write_project_env(str(tmp_path), answers)
    repo_root = Path(__file__).resolve().parents[1]
    env_rel = ".env"
    # The project's shipped ignore rules must ignore `.env`.
    import subprocess

    proc = subprocess.run(
        ["git", "check-ignore", "-q", env_rel],
        cwd=repo_root,
    )
    assert proc.returncode == 0
