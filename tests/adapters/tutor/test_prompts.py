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


@pytest.mark.parametrize("name", ["tutor_math", "rubric_judge"])
def test_candidate_v2_policy_resolves_without_changing_v1(name):
    from learnai.adapters.tutor.prompts import PROMPTS_ROOT

    prompt = load_prompt(f"{name}@2")
    assert prompt.id == f"{name}@2"
    assert prompt.text == (PROMPTS_ROOT / name / "v2.md").read_text(encoding="utf-8")
    assert prompt.text != load_prompt(f"{name}@1").text


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
@pytest.mark.parametrize("role,name", [("tutor", "tutor_math"), ("judge", "rubric_judge")])
def test_provider_request_contains_exact_selected_v2_policy(provider, role, name):
    from learnai.adapters.content.registry import GeneratorRegistry
    from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
    from learnai.adapters.tutor.openai.wiring import OpenAIFactory
    from learnai.adapters.tutor.prompts import PROMPTS_ROOT
    from learnai.adapters.tutor.rendering import render_skill_pack
    from learnai.adapters.tutor.routing import Route
    from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES
    from learnai.application.ports import TutorDependencies
    from tests.eval.test_judge import packet

    factory = AnthropicFactory() if provider == "anthropic" else OpenAIFactory()
    route = Route("selected", provider, "scripted", effort="low", prompt=f"{name}@2",
                  budget_profile="substantial")
    config = factory.resolve_config(route, role=role, profiles=DEFAULT_BUDGET_PROFILES,
                                    prompts_root=PROMPTS_ROOT)
    p = packet()
    prepared = (factory.prepare_judge(config, packet=p) if role == "judge" else
                factory.prepare_tutor(config, context=p.context,
                    dependencies=TutorDependencies(GeneratorRegistry(()), {})))
    assert prepared.admitted
    expected = (PROMPTS_ROOT / name / "v2.md").read_text(encoding="utf-8")
    if provider == "openai":
        if role == "tutor":
            expected += "\n\n" + render_skill_pack(p.context)
        assert prepared.payload["instructions"] == expected
    else:
        policy = (prepared.payload["system"] if role == "judge" else
                  prepared.payload["system"][0]["text"])
        assert policy == expected
