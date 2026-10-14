# tests/test_domain_purity.py
import ast
import pathlib

ALLOWED_TOP_LEVEL = {
    "learnai",
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


def test_domain_imports_only_stdlib_and_itself():
    offenders: dict[str, set[str]] = {}
    for path in DOMAIN.rglob("*.py"):
        bad = _imported_roots(path) - ALLOWED_TOP_LEVEL
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"domain core must stay pure, found: {offenders}"


def test_domain_never_imports_forbidden_packages():
    for path in DOMAIN.rglob("*.py"):
        assert not (_imported_roots(path) & FORBIDDEN), f"{path.name} imports a forbidden package"
