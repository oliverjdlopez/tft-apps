from __future__ import annotations

import ast
import importlib.util
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


def _runtime_import_graph() -> dict[str, set[str]]:
    modules = {_module_name(path): path for path in _runtime_files()}
    graph = {name: set() for name in modules}
    for name, path in modules.items():
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
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


def test_runtime_module_dependencies_are_acyclic() -> None:
    graph = _runtime_import_graph()
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in visiting:
            start = visiting.index(module)
            cycle = [*visiting[start:], module]
            raise AssertionError("runtime import cycle: " + " -> ".join(cycle))
        if module in visited:
            return
        visiting.append(module)
        for dependency in graph[module]:
            visit(dependency)
        visiting.pop()
        visited.add(module)

    for module in graph:
        visit(module)
