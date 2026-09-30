"""Create, inspect, and retire assistant specs without making model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from .utils import removal_dependencies, spec_inventory, validate_name


def create_spec(root: Path, name: str, *, prompt: str | None = None,
                copy_from: str | None = None) -> dict:
    """Create a validated new directory, optionally copying an existing spec.

    Args:
        root: Repository assistant-spec directory.
        name: New assistant and directory identity.
        prompt: Authored instructions, required unless copying a spec.
        copy_from: Existing assistant to duplicate, without copying its evals.

    Returns:
        Created identity and source path.
    """
    from domain.assistants import load_assistant_spec, resolve_assistant_tools

    validate_name(name)
    specs = spec_inventory(root)
    destination = root / name
    if name.casefold() in {key.casefold() for key in specs} or destination.exists():
        raise ValueError(f"Assistant or directory already exists: {name}")
    if prompt is not None and not prompt.strip():
        raise ValueError("The system prompt cannot be empty.")
    if copy_from is None and prompt is None:
        raise ValueError("Supply --prompt-file or --copy-from.")
    if copy_from is not None and copy_from not in specs:
        raise ValueError(f"Unknown source assistant: {copy_from}")
    # Stage on the same filesystem; rename publishes a complete spec directory.
    with tempfile.TemporaryDirectory(prefix=".new-spec-", dir=root.parent) as temporary:
        candidate = Path(temporary) / name
        candidate.mkdir()
        if copy_from is not None:
            source, original = specs[copy_from]
            if not source.is_dir():
                raise ValueError("Copying legacy single-file specs is unsupported; supply --prompt-file.")
            for filename in ("system.md", "agent.json", "task.md"):
                if (source / filename).is_file():
                    shutil.copy2(source / filename, candidate / filename)
            # Normalize old frontmatter-based definitions as well as agent.json.
            config = {"description": original.description,
                      "handoff_description": original.handoff_description,
                      "tools": {"include_all": original.include_all_tools,
                                "groups": list(original.tool_group_keys), "names": list(original.tool_names)},
                      "context": {"repository": original.repository_context},
                      "handoffs": list(original.handoff_names)}
            if original.model is not None:
                config["model"] = original.model.value
            if original.reasoning is not None:
                config["reasoning"] = original.reasoning.value
            if original.skill_names is not None:
                config["skills"] = list(original.skill_names)
            (candidate / "system.md").write_text(original.system_prompt + "\n", encoding="utf-8")
            if original.task_prompt:
                (candidate / "task.md").write_text(original.task_prompt + "\n", encoding="utf-8")
        else:
            config = {"description": name, "tools": {"groups": [], "names": []},
                      "handoffs": [], "skills": [], "context": {"repository": False}}
        config["name"] = name
        (candidate / "agent.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        if prompt is not None:
            (candidate / "system.md").write_text(prompt, encoding="utf-8")
        spec = load_assistant_spec(candidate, root_dir=candidate.parent)
        if spec.name != name or not spec.system_prompt.strip():
            raise ValueError("The created spec must retain its requested name and a nonempty prompt.")
        missing = set(spec.handoff_names) - set(specs)
        if missing:
            raise ValueError(f"Unknown handoff targets: {sorted(missing)}")
        resolve_assistant_tools(spec)
        candidate.rename(destination)
    return {"created": name, "path": str(destination)}


def remove_spec(root: Path, repo: Path, name: str, *, apply: bool = False,
                backup_dir: Path | None = None) -> dict:
    """Preview removal or move an unreferenced spec into a recoverable backup.

    Args:
        root: Repository assistant-spec directory.
        repo: Checkout root used to inspect callers and active eval definitions.
        name: Registered assistant to retire.
        apply: Whether to perform the previewed operation.
        backup_dir: Explicit parent directory for a uniquely named backup.

    Returns:
        Removal plan, blockers, and backup location when applied.
    """
    validate_name(name)
    specs = spec_inventory(root)
    if name not in specs:
        raise ValueError(f"Unknown assistant: {name}")
    source, _ = specs[name]
    if not source.is_dir():
        raise ValueError("Retire legacy single-file specs manually.")
    blockers = removal_dependencies(name, specs, repo)
    result = {"assistant": name, "path": str(source), "blockers": blockers, "applied": False}
    if not apply:
        return result
    if blockers:
        raise ValueError("Resolve removal dependencies first:\n" + "\n".join(blockers))
    if backup_dir is None:
        raise ValueError("Removal requires --backup-dir so the complete spec can be recovered.")
    if backup_dir.resolve().is_relative_to(root.resolve()):
        raise ValueError("The backup directory must be outside assistant_specs.")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=backup_dir))
    shutil.move(str(source), str(backup / name))
    return {**result, "applied": True, "backup": str(backup / name)}


def main(argv: list[str] | None = None) -> int:
    """Dispatch terminal management commands independently of assistant execution."""
    from domain.assistants.specs import ASSISTANT_SPECS_DIR, ROOT_DIR

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List repository assistant definitions.")
    create = commands.add_parser("create", help="Create a new spec or copy an existing one.")
    create.add_argument("name")
    create.add_argument("--prompt-file", type=Path)
    create.add_argument("--copy-from")
    remove = commands.add_parser("remove", help="Preview dependencies; --apply backs up and removes the spec.")
    remove.add_argument("name")
    remove.add_argument("--apply", action="store_true")
    remove.add_argument("--backup-dir", type=Path)
    sync = commands.add_parser("sync-langfuse", help="Preview missing prompts and explicitly named retired prompts.")
    sync.add_argument("--remove", action="append", default=[], metavar="ASSISTANT")
    sync.add_argument("--apply", action="store_true")
    sync.add_argument("--backup-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            result = {name: str(path) for name, (path, _) in spec_inventory(ASSISTANT_SPECS_DIR).items()}
        elif args.command == "create":
            result = create_spec(ASSISTANT_SPECS_DIR, args.name, copy_from=args.copy_from,
                                 prompt=args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else None)
        elif args.command == "remove":
            result = remove_spec(ASSISTANT_SPECS_DIR, ROOT_DIR, args.name,
                                 apply=args.apply, backup_dir=args.backup_dir)
        else:
            from evals.langfuse.prompts import sync_prompts
            result = sync_prompts(remove=args.remove, apply=args.apply, backup_dir=args.backup_dir)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Assistant specs: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
