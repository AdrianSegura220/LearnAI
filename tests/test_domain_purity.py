# tests/test_domain_purity.py
import ast
import pathlib

ALLOWED_TOP_LEVEL = {
    "collections", "dataclasses", "datetime", "enum", "math", "typing",
    "abc", "functools", "itertools", "uuid", "random", "re",
}
FORBIDDEN = {"sympy", "yaml", "anthropic", "sqlalchemy", "fastapi", "requests", "httpx", "os", "pathlib"}

DOMAIN = pathlib.Path(__file__).parent.parent / "src" / "learnai" / "domain"


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _purity_violations(source: str) -> set[str]:
    """Absolute module paths in `source` that break the domain boundary.

    Standard library imports are allowed, and of `learnai` only the `domain`
    package itself: a domain module importing `learnai.adapters` or
    `learnai.content` is exactly the violation this checker exists to catch,
    so the full module path is inspected, never just the root.
    """
    violations: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules = [node.module]
        else:
            continue
        for module in modules:
            if module == "learnai.domain" or module.startswith("learnai.domain."):
                continue
            if module.split(".")[0] not in ALLOWED_TOP_LEVEL:
                violations.add(module)
    return violations


def test_domain_imports_only_stdlib_and_itself():
    offenders: dict[str, set[str]] = {}
    for path in DOMAIN.rglob("*.py"):
        bad = _purity_violations(path.read_text())
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"domain core must stay pure, found: {offenders}"


def test_the_checker_flags_sibling_packages_and_permits_domain_internals():
    assert _purity_violations(
        "from learnai.adapters.cas.parse import parse_math"
    ) == {"learnai.adapters.cas.parse"}
    assert _purity_violations("from learnai.domain.ids import SkillId") == set()
    assert _purity_violations("import learnai.content.loader") == {"learnai.content.loader"}


def test_domain_never_imports_forbidden_packages():
    for path in DOMAIN.rglob("*.py"):
        assert not (_imported_roots(path) & FORBIDDEN), f"{path.name} imports a forbidden package"
