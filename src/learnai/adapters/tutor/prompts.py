"""Load versioned policy text with explicit prompt provenance."""

from dataclasses import dataclass
from pathlib import Path
import re


PROMPTS_ROOT = Path(__file__).resolve().parents[4] / "prompts"
_REFERENCE = re.compile(r"([a-z][a-z0-9_]*)@([1-9][0-9]*)")


class PromptError(ValueError):
    """A prompt reference or its versioned file is invalid."""


@dataclass(frozen=True, slots=True)
class TutorPrompt:
    name: str
    version: int
    path: Path
    text: str

    @property
    def id(self) -> str:
        return f"{self.name}@{self.version}"


def _parse_reference(reference: str) -> tuple[str, int]:
    match = _REFERENCE.fullmatch(reference) if isinstance(reference, str) else None
    if match is None:
        raise PromptError(f"invalid prompt reference: {reference!r}")
    return match[1], int(match[2])


def load_prompt(reference: str, *, root: Path = PROMPTS_ROOT) -> TutorPrompt:
    """Read an exact prompt version; never fall back to another version."""
    name, version = _parse_reference(reference)
    resolved_root = root.resolve()
    path = (resolved_root / name / f"v{version}.md").resolve()
    if not path.is_relative_to(resolved_root):
        raise PromptError(f"prompt escapes root: {reference}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PromptError(f"cannot read prompt {reference}: {exc}") from exc
    if not text.strip():
        raise PromptError(f"empty prompt: {reference}")
    return TutorPrompt(name=name, version=version, path=path, text=text)
