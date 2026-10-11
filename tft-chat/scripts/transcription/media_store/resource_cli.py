"""Publish, discover, inspect, and pull shared artifacts from either repository."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .resources import ResourceStore


def main() -> None:
    """Expose the resource protocol to local scripts without app dependencies."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("file", type=Path)
    publish.add_argument("--kind", required=True, choices=["text", "data", "image", "audio", "video"])
    publish.add_argument("--source", required=True)
    publish.add_argument("--name")
    publish.add_argument("--content-type", default="application/octet-stream")
    publish.add_argument("--metadata", type=json.loads, default={})
    find = commands.add_parser("list")
    find.add_argument("--source")
    find.add_argument("--kind")
    find.add_argument("--name")
    find.add_argument("--limit", type=int, default=100)
    find.add_argument("--offset", type=int, default=0)
    commands.add_parser("get").add_argument("reference")
    commands.add_parser("resolve").add_argument("reference")
    pull = commands.add_parser("pull")
    pull.add_argument("reference")
    pull.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        store = ResourceStore.from_env()
        if store is None:
            parser.error("Set TFT_MEDIA_DIR to the shared catalog directory")
        if args.command == "publish":
            result = store.publish(args.file, kind=args.kind, source=args.source, name=args.name,
                                   content_type=args.content_type, metadata=args.metadata)
            print(json.dumps({**asdict(result), "reference": result.reference}))
        elif args.command == "list":
            print(json.dumps([{**asdict(item), "reference": item.reference} for item in store.find(
                source=args.source, kind=args.kind, name=args.name, limit=args.limit, offset=args.offset)]))
        elif args.command == "get":
            result = store.get(args.reference)
            print(json.dumps({**asdict(result), "reference": result.reference}))
        elif args.command == "resolve":
            print(store.resolve(args.reference))
        else:
            print(store.pull(args.reference, args.destination))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
