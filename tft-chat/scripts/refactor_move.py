"""Move a top-level Python symbol with Rope and update project references."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Move one top-level Python symbol with Rope. Dry-run by default."
    )
    parser.add_argument("source", type=Path, help="Source Python module path")
    parser.add_argument("symbol", help="Top-level function, class, or variable name")
    parser.add_argument("destination", type=Path, help="Existing destination module path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the change set; otherwise print Rope's preview",
    )
    return parser


def _symbol_offset(source: str, symbol: str) -> int:
    tree = ast.parse(source)
    matches: list[ast.AST] = []
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == symbol
        ):
            matches.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == symbol
            for target in node.targets
        ):
            matches.append(node)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == symbol
        ):
            matches.append(node)
    if len(matches) != 1:
        raise ValueError(
            f"expected one top-level symbol named {symbol!r}, found {len(matches)}"
        )
    node = matches[0]
    lines = source.splitlines(keepends=True)
    definition_line = lines[node.lineno - 1]
    name_column = definition_line.find(symbol, node.col_offset)
    if name_column < 0:
        raise ValueError(f"could not locate {symbol!r} on its definition line")
    return sum(len(line) for line in lines[: node.lineno - 1]) + name_column


def move_symbol(
    project_root: Path,
    source_path: Path,
    symbol: str,
    destination_path: Path,
    *,
    apply: bool,
) -> str:
    try:
        from rope.base.project import Project
        from rope.refactor.move import create_move
    except ImportError as exc:
        raise RuntimeError(
            "Rope is required; run with `uv run --extra refactor "
            "tft-refactor-move ...`"
        ) from exc

    root = project_root.resolve()
    source_relative = source_path.resolve().relative_to(root)
    destination_relative = destination_path.resolve().relative_to(root)
    project = Project(
        str(root),
        ropefolder=None,
        source_folders=["app/backend", "app/backend/src", "."],
    )
    try:
        source_resource = project.get_file(source_relative.as_posix())
        destination_resource = project.get_file(destination_relative.as_posix())
        offset = _symbol_offset(source_resource.read(), symbol)
        changes = create_move(project, source_resource, offset).get_changes(
            destination_resource
        )
        description = changes.get_description()
        if apply:
            project.do(changes)
        return description
    finally:
        project.close()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    root = Path.cwd()
    print(
        move_symbol(
            root,
            args.source,
            args.symbol,
            args.destination,
            apply=args.apply,
        )
    )


if __name__ == "__main__":
    main()
