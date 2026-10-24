"""Copy suite dotenv defaults into marked sections of application dotenv files."""

from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile

from dotenv.parser import Binding, parse_stream

BEGIN = "# BEGIN GENERATED SHARED SETTINGS"
END = "# END GENERATED SHARED SETTINGS"


def bindings(text: str, path: Path) -> list[Binding]:
    """Parse dotenv records without exposing values in validation errors.

    Args:
        text: Original dotenv content, including comments and quoting.
        path: File identified in diagnostics.

    Returns:
        Validated records retaining their original source text.
    """
    records = list(parse_stream(io.StringIO(text)))
    if any(record.error for record in records):
        raise ValueError(f"Invalid dotenv syntax in {path}")
    return records


def render(shared: str, original: str, path: Path) -> str:
    """Replace generated defaults while preserving all manually maintained text.

    Args:
        shared: Root dotenv source.
        original: Existing application dotenv source.
        path: Application file used for safe diagnostics.

    Returns:
        Updated dotenv content with app-specific keys excluded from defaults.
    """
    # Only standalone comment records are markers, never lines inside values.
    records = bindings(original, path)
    starts = [i for i, record in enumerate(records) if record.original.string.strip() == BEGIN]
    ends = [i for i, record in enumerate(records) if record.original.string.strip() == END]
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise ValueError(f"Invalid generated dotenv section in {path}")
        # The parser attaches preceding blank lines to a comment record. Keep
        # those user-authored bytes when removing the generated section.
        marker = records[starts[0]]
        prefix = marker.original.string[:marker.original.string.index(BEGIN)]
        records = records[:starts[0]] + bindings(prefix, path) + records[ends[0] + 1:]
    manual = ''.join(record.original.string for record in records)
    overrides = {record.key for record in records if record.key is not None}
    defaults = ''.join(record.original.string for record in bindings(shared, path.parent.parent / '.env')
                       if record.key is not None and record.key not in overrides)
    if not defaults:
        return manual
    separator = '' if not manual or manual.endswith('\n') else '\n'
    return manual + separator + BEGIN + '\n' + defaults.rstrip('\r\n') + '\n' + END + '\n'


def sync(suite: Path) -> None:
    """Validate both app files before atomically replacing changed contents.

    Args:
        suite: Suite checkout root, independent of the terminal directory.
    """
    root = suite / '.env'
    shared = root.read_bytes().decode('utf-8') if root.exists() else ''
    bindings(shared, root)
    pending = []
    for app in ('tft-chat', 'vod-review'):
        destination = suite / app / '.env'
        if destination.is_symlink():
            raise ValueError(f'Cannot sync symlinked dotenv file: {destination}')
        original = destination.read_bytes().decode('utf-8') if destination.exists() else ''
        updated = render(shared, original, destination)
        if updated != original:
            pending.append((destination, updated))

    # Same-directory replacement avoids partial files and creates private files.
    for destination, updated in pending:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=destination.parent,
                                             prefix='.env-', delete=False) as output:
                temporary = Path(output.name)
                output.write(updated)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        sync(Path(__file__).resolve().parent.parent)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from None
