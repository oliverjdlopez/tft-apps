from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator

import pytest
from pathlib import Path

from core.config import load_config


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOTS = (ROOT / "app", ROOT / "scripts", ROOT / "evals", ROOT / "connectivity_check.py")
LEGACY_PROJECT_PREFIX = "TFT" + "_CHAT"
RETIRED_NAMES = (
    f"{LEGACY_PROJECT_PREFIX}_DATABASE_URL",
    f"{LEGACY_PROJECT_PREFIX}_EVAL_DB_URL",
    "TFT_EVAL_DB_",
    "RDS_SOURCE_INSTANCE_ID",
    "OPENAI_MODEL",
    f"{LEGACY_PROJECT_PREFIX}_UI_HOST",
    f"{LEGACY_PROJECT_PREFIX}_UI_PORT",
    f"{LEGACY_PROJECT_PREFIX}_REBUILD_TABLES_ON_STARTUP",
    "postgresql:///",
)
RETIRED_NAME_EXCEPTIONS = {
    # This maintenance command's entire purpose is an explicit RDS-to-local
    # copy; the URL is never used as an application runtime fallback.
    "postgresql:///": {ROOT / "scripts" / "download_rds.py"},
}


def _runtime_files() -> list[Path]:
    files: list[Path] = []
    for root in RUNTIME_ROOTS:
        if root.is_file():
            files.append(root)
        else:
            files.extend(path for path in root.rglob("*.py") if "node_modules" not in path.parts)
    return files


def test_runtime_does_not_contain_retired_database_contracts() -> None:
    violations = {
        f"{path.relative_to(ROOT)}: {name}"
        for path in _runtime_files()
        for name in RETIRED_NAMES
        if name in path.read_text(encoding="utf-8")
        and path not in RETIRED_NAME_EXCEPTIONS.get(name, set())
    }
    assert not violations, "\n".join(sorted(violations))


def test_tracked_ini_example_is_parseable() -> None:
    load_config(ROOT / "chat_tft.ini.example")


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT)
    parts = relative.parts
    if parts[:2] == ("app", "backend"):
        parts = parts[2:]
        if parts and parts[0] == "src":
            parts = parts[1:]
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts = (*parts[:-1], parts[-1].removesuffix(".py"))
    return ".".join(parts)


def _runtime_import_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    """Yield runtime imports, including deferred imports but excluding type guards.

    Args:
        tree: Parsed module or statement to inspect.

    Yields:
        Imports that can execute, including runtime branches of type guards.
    """
    if isinstance(tree, ast.If):
        condition = tree.test
        negated = isinstance(condition, ast.UnaryOp) and isinstance(condition.op, ast.Not)
        guard = condition.operand if negated else condition
        type_checking = (
            isinstance(guard, ast.Name) and guard.id == "TYPE_CHECKING"
            or isinstance(guard, ast.Attribute)
            and isinstance(guard.value, ast.Name)
            and guard.value.id == "typing" and guard.attr == "TYPE_CHECKING"
        )
        if type_checking:
            for statement in tree.body if negated else tree.orelse:
                yield from _runtime_import_nodes(statement)
            return
    if isinstance(tree, (ast.Import, ast.ImportFrom)):
        yield tree
    for child in ast.iter_child_nodes(tree):
        yield from _runtime_import_nodes(child)


def _runtime_import_graph() -> dict[str, set[str]]:
    """Resolve runtime import edges to their repository module owners."""
    modules = {_module_name(path): path for path in _runtime_files()}
    graph = {name: set() for name in modules}
    for name, path in modules.items():
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in _runtime_import_nodes(ast.parse(path.read_text(encoding="utf-8"))):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                try:
                    base = (
                        importlib.util.resolve_name(
                            "." * node.level + (node.module or ""), package
                        )
                        if node.level
                        else (node.module or "")
                    )
                except (ImportError, ValueError):
                    continue
                targets = [base]
                targets.extend(
                    f"{base}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
            for target in targets:
                matches = [
                    module
                    for module in modules
                    if target == module or target.startswith(f"{module}.")
                ]
                if matches:
                    dependency = max(matches, key=len)
                    if dependency != name:
                        graph[name].add(dependency)
    return graph


def _cyclic_components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Find every strongly connected import group in deterministic order.

    Args:
        graph: Module names mapped to their imported repository dependencies.

    Returns:
        Sorted groups containing cycles, with each module reported once.
    """
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    groups: list[tuple[str, ...]] = []

    def visit(module: str) -> None:
        """Complete one Tarjan traversal, retaining unresolved components."""
        indices[module] = lowlinks[module] = len(indices)
        stack.append(module)
        active.add(module)
        for dependency in sorted(graph[module]):
            if dependency not in indices:
                visit(dependency)
                lowlinks[module] = min(lowlinks[module], lowlinks[dependency])
            elif dependency in active:
                lowlinks[module] = min(lowlinks[module], indices[dependency])
        if lowlinks[module] != indices[module]:
            return
        component = []
        while True:
            member = stack.pop()
            active.remove(member)
            component.append(member)
            if member == module:
                break
        if len(component) > 1 or module in graph[module]:
            groups.append(tuple(sorted(component)))

    for module in sorted(graph):
        if module not in indices:
            visit(module)
    return sorted(groups)


def test_runtime_module_dependencies_are_acyclic() -> None:
    """Report every dependency cycle, including imports deferred inside functions."""
    groups = _cyclic_components(_runtime_import_graph())
    assert not groups, "Runtime import dependency cycles:\n" + "\n".join(
        "  " + ", ".join(group) for group in groups
    )


def test_import_guard_keeps_deferred_and_runtime_else_imports() -> None:
    """Type-only cycles are excluded without hiding deferred execution edges."""
    tree = ast.parse("""
from typing import TYPE_CHECKING
import typing
if TYPE_CHECKING:
    import type_only
else:
    import runtime_else
if typing.TYPE_CHECKING:
    import qualified_type_only
if not TYPE_CHECKING:
    import runtime_body
else:
    import negated_type_only
def load():
    import deferred
""")
    imports = {
        alias.name
        for node in _runtime_import_nodes(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imports == {"typing", "runtime_else", "runtime_body", "deferred"}


def test_import_guard_reports_all_disjoint_cycles() -> None:
    """Independent cycles are diagnosed together, without including their callers."""
    graph = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"},
             "caller": {"a", "c"}, "leaf": set(), "self": {"self"}}
    assert _cyclic_components(graph) == [("a", "b"), ("c", "d"), ("self",)]


def test_resource_library_has_no_assistant_dependencies() -> None:
    """Keep storage and loading independent of assistant policy and presentation."""
    forbidden = ('agents', 'domain.assistants', 'domain.runtime', 'domain.tools')
    violations = []
    for path in (ROOT / 'app/backend/src/domain/resources').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
            for module in modules:
                if any(module == prefix or module.startswith(prefix + '.') for prefix in forbidden):
                    violations.append(f'{path.name}:{node.lineno}: {module}')
    assert not violations, '\n'.join(violations)


@pytest.mark.parametrize("module", [
    "domain.resources.library", "domain.assistants.resources",
    "domain.assistants", "domain.assistants.assistant",
    "domain.compositions.acceleration", "domain.compositions.reference",
    "services.compositions.persistence", "services.compositions.utils",
    "scripts.transcription.download_vod", "scripts.transcription.shared_download",
    "evals.langfuse.utils", "evals.langfuse.content",
    "evals.langfuse.assistant_workspace", "evals.langfuse.workspace",
    "evals.langfuse.prompts", "evals.langfuse.seed",
])
def test_runtime_entry_imports_in_fresh_process(module: str, tmp_path: Path) -> None:
    """Import each boundary first so pytest's module cache cannot conceal cycles."""
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(str(path) for path in (
        ROOT, ROOT / "app/backend", ROOT / "app/backend/src",
    ))}
    result = subprocess.run(
        [sys.executable, "-c", "import importlib, sys; importlib.import_module(sys.argv[1])", module],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
