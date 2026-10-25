import pytest

from learnai.adapters.tutor.prompts import PromptError, load_prompt


def test_prompt_loads_versioned_text_and_provenance(tmp_path):
    directory = tmp_path / "tutor_math"
    directory.mkdir()
    path = directory / "v12.md"
    path.write_text("  Teach carefully.\n", encoding="utf-8")
    prompt = load_prompt("tutor_math@12", root=tmp_path)
    assert (prompt.name, prompt.version, prompt.id) == ("tutor_math", 12, "tutor_math@12")
    assert prompt.path == path
    assert prompt.text == "  Teach carefully.\n"


@pytest.mark.parametrize("reference", [
    "../tutor_math@1", "tutor/math@1", "Tutor@1", "1tutor@1", "tutor-math@1",
    "tutor_math@0", "tutor_math@01", "tutor_math@-1", "tutor_math", "tutor_math@1\n",
    "tutor_math@1/../../secret", "tutor_math@1.0", "", None,
])
def test_invalid_prompt_reference_fails(tmp_path, reference):
    with pytest.raises(PromptError):
        load_prompt(reference, root=tmp_path)


def test_missing_prompt_fails(tmp_path):
    with pytest.raises(PromptError, match="tutor_math@1"):
        load_prompt("tutor_math@1", root=tmp_path)


@pytest.mark.parametrize("text", ["", " \n\t"])
def test_empty_prompt_fails(tmp_path, text):
    (tmp_path / "tutor_math").mkdir()
    (tmp_path / "tutor_math" / "v1.md").write_text(text, encoding="utf-8")
    with pytest.raises(PromptError):
        load_prompt("tutor_math@1", root=tmp_path)


def test_prompt_symlink_cannot_escape_root(tmp_path):
    root = tmp_path / "prompts"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "v1.md").write_text("Private text", encoding="utf-8")
    (root / "tutor_math").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PromptError):
        load_prompt("tutor_math@1", root=root)
