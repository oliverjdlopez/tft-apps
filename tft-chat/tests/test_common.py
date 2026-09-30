from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from common.access import field_value
from common.discoverers import discover_files
from common.loaders import load_unique
from common.parsers import (
    first_markdown_heading,
    parse_frontmatter,
    parse_string_list,
)
from common.paths import find_repo_root
from common.secrets import redact_url_credentials
from common.serialization import (
    model_jsonable,
    read_json_lines,
    render_json_preview,
    to_jsonable,
    truncate_json,
    write_json_lines,
)
from common.sql import quote_identifier
from scripts.refactor_move import _symbol_offset


@dataclass
class _Record:
    name: str


def test_field_value_supports_mappings_and_objects() -> None:
    assert field_value({"name": "mapping"}, "name") == "mapping"
    assert field_value(_Record("object"), "name") == "object"
    assert field_value({}, "missing", "fallback") == "fallback"


def test_markdown_parsers_handle_frontmatter_lists_and_heading() -> None:
    parsed = parse_frontmatter(
        "---\r\nName: sample\r\nkeywords: 'one', two\r\n---\r\n# Heading\r\n"
    )

    assert parsed.metadata == {"name": "sample", "keywords": "'one', two"}
    assert first_markdown_heading(parsed.body) == "Heading"
    assert parse_string_list(parsed.metadata["keywords"], casefold=True) == (
        "one",
        "two",
    )


def test_discovery_and_unique_loading_are_deterministic(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("same", encoding="utf-8")
    (tmp_path / "a.md").write_text("same", encoding="utf-8")
    (tmp_path / "README.md").write_text("ignored", encoding="utf-8")
    duplicates: list[Path] = []

    paths = discover_files(tmp_path, ["*.md"], skip_names={"readme.md"})
    loaded = load_unique(
        paths,
        lambda path: (path.name, path.read_text(encoding="utf-8")),
        identity=lambda item: item[1],
        on_duplicate=lambda path, _item: duplicates.append(path),
    )

    assert [path.name for path in paths] == ["a.md", "b.md"]
    assert loaded == [("a.md", "same")]
    assert duplicates == [tmp_path / "b.md"]


def test_json_helpers_convert_preview_truncate_and_round_trip(tmp_path: Path) -> None:
    value = {"path": tmp_path, "items": (1, 2)}

    assert to_jsonable(value) == {"path": str(tmp_path), "items": [1, 2]}
    assert model_jsonable(
        {"rate": 0.12345, "count": 7, "nested": [2.987], "decimal": Decimal("4.567")}
    ) == {
        "rate": 0.12,
        "count": 7,
        "nested": [2.99],
        "decimal": 4.57,
    }
    assert render_json_preview(value, max_chars=12).endswith("\n...")
    assert truncate_json(value, max_bytes=12)["truncated"] is True

    path = tmp_path / "events.jsonl"
    write_json_lines(path, [{"one": 1}, {"two": tmp_path}])
    write_json_lines(path, [{"three": 3}], append=True)
    assert read_json_lines(path) == [
        {"one": 1},
        {"two": str(tmp_path)},
        {"three": 3},
    ]


def test_path_sql_and_secret_helpers() -> None:
    root = find_repo_root(Path(__file__))

    assert (root / "pyproject.toml").is_file()
    assert quote_identifier('odd"name') == '"odd""name"'
    assert redact_url_credentials(
        "postgresql://user:secret@example.test/db?sslmode=require&password=query"
    ) == (
        "postgresql://user:<redacted>@example.test/db"
        "?sslmode=require&password=%3Credacted%3E"
    )


def test_find_repo_root_rejects_unrelated_tree(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_repo_root(tmp_path)


def test_refactor_cli_locates_only_top_level_symbols() -> None:
    source = "SETTING: int = 1\n\ndef target() -> None:\n    pass\n"

    assert _symbol_offset(source, "target") == source.index("target")
    assert _symbol_offset(source, "SETTING") == source.index("SETTING")
    with pytest.raises(ValueError):
        _symbol_offset(source, "missing")
