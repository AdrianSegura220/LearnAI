import subprocess
import sys


def test_saved_artifact_imports_and_registry_metadata_are_sdk_free(tmp_path):
    script = '''
import sys
class BlockSDK:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'anthropic', 'openai', 'httpx', 'httpx2'}:
            raise AssertionError('SDK imported: ' + fullname)
sys.meta_path.insert(0, BlockSDK())
from pathlib import Path
from learnai.application.artifacts import load_saved_run
from learnai.eval.report import compare_runs
from learnai.application.providers import default_registry
from learnai.eval.__main__ import main
saved = load_saved_run(Path('tests/fixtures/eval_v1/run'))
assert compare_runs(saved, saved)
factory = default_registry().get('anthropic')
assert factory.api_family == 'messages'
from learnai.eval.accounting import RequestLedger, PriceBook
from learnai.eval.manifest import build_manifest
from learnai.eval.report import write_report
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.routing import Route
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES
for role in ('tutor', 'judge'):
    config = factory.resolve_config(Route('selected', 'anthropic', 'fictional', prompt='rubric_judge@1'),
        role=role, profiles=DEFAULT_BUDGET_PROFILES, prompts_root=PROMPTS_ROOT)
    assert config.schema_hashes
root = Path(sys.argv[1])
manifest = build_manifest(root=root, selected_ids=tuple(saved.packets), seeds=(), settings={}, prompts={}, references={})
v2_path = write_report(root, manifest=manifest, outcomes={}, scores={}, judge_packets=saved.packets,
                      ledger=RequestLedger(), prices=PriceBook(()), persona_smoke={})
v2 = load_saved_run(v2_path)
assert v2.packets == saved.packets
assert compare_runs(saved, v2)
assert not {'anthropic', 'openai', 'httpx', 'httpx2'} & sys.modules.keys()
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_shared_evaluation_and_contracts_never_import_sdk_or_provider_packages():
    import ast
    from pathlib import Path
    root = Path('src/learnai')
    paths = [*root.joinpath('eval').glob('*.py'), root / 'application/ports.py',
             root / 'application/tutor_router.py', root / 'adapters/tutor/configuration.py']
    forbidden = ('anthropic', 'openai', 'httpx', 'httpx2',
                 'learnai.adapters.tutor.anthropic', 'learnai.adapters.tutor.openai')
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            assert not any(module == prefix or module.startswith(prefix + '.')
                           for module in modules for prefix in forbidden), path
