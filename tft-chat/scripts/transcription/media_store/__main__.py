"""Import existing local downloads into the shared catalog without remote I/O."""

import argparse
from pathlib import Path

from . import MediaStore
from .models import MediaRequest


def main() -> None:
    """Register a file with explicit source, coverage, and quality provenance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--kind", choices=["audio", "video"], required=True)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float, help="Source end time; omit only for a file reaching source EOF")
    parser.add_argument("--profile", required=True, help="Original selection: audio, video:720p, video:best, or selector:...")
    args = parser.parse_args()
    store = MediaStore.from_env()
    if store is None:
        parser.error("Set TFT_MEDIA_DIR to the shared catalog directory")
    if not args.file.is_file():
        parser.error("The local media file does not exist")
    print(store.obtain(MediaRequest(args.url, args.kind, args.start, args.end, args.profile), lambda: args.file))


if __name__ == "__main__":
    main()
