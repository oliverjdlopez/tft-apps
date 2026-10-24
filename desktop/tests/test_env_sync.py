"""Verify generated defaults preserve application-specific configuration."""

import io
from pathlib import Path

from dotenv import dotenv_values
import pytest

from desktop.env_sync import BEGIN, END, render, sync


def test_overrides_updates_and_removals(tmp_path: Path) -> None:
    """Keep app overrides separate and remove stale generated settings."""
    for app in ('tft-chat', 'vod-review'):
        (tmp_path / app).mkdir()
    chat = tmp_path / 'tft-chat/.env'
    vod = tmp_path / 'vod-review/.env'
    chat.write_text('# My settings\nKEY=chat\nEMPTY=\n')
    root = tmp_path / '.env'
    root.write_text('KEY=shared\nEMPTY=default\nMULTI="first\nsecond"\n')
    sync(tmp_path)
    assert dotenv_values(chat) == {'KEY': 'chat', 'EMPTY': '', 'MULTI': 'first\nsecond'}
    assert dotenv_values(vod)['KEY'] == 'shared'
    assert chat.read_text().startswith('# My settings\nKEY=chat\nEMPTY=\n')
    before = chat.stat().st_mtime_ns
    sync(tmp_path)
    assert chat.stat().st_mtime_ns == before
    root.write_text('KEY=changed\n')
    sync(tmp_path)
    assert dotenv_values(chat) == {'KEY': 'chat', 'EMPTY': ''}
    assert dotenv_values(vod) == {'KEY': 'changed'}
    root.unlink()
    sync(tmp_path)
    assert vod.read_text() == ''
    assert 'KEY=chat' in chat.read_text()


def test_manual_settings_after_block_and_quoted_values() -> None:
    """Honor manual keys and retain dotenv quoting and interpolation."""
    original = f'{BEGIN}\nOLD=gone\n{END}\nexport KEY=local\n'
    shared = 'KEY=root\nTEXT="a # b"\nCOPY=${KEY}\n'
    result = render(shared, original, Path('/suite/vod-review/.env'))
    assert dotenv_values(stream=io.StringIO(result)) == {'KEY': 'local', 'TEXT': 'a # b', 'COPY': 'local'}
    assert render(shared, result, Path('/suite/vod-review/.env')) == result


def test_invalid_file_does_not_modify_other_app(tmp_path: Path) -> None:
    """Reject damaged markers or syntax before writing either application file."""
    for app in ('tft-chat', 'vod-review'):
        (tmp_path / app).mkdir()
    (tmp_path / '.env').write_text('KEY=value\n')
    (tmp_path / 'vod-review/.env').write_text(BEGIN + '\n')
    with pytest.raises(ValueError, match='Invalid generated dotenv section'):
        sync(tmp_path)
    assert not (tmp_path / 'tft-chat/.env').exists()
    with pytest.raises(ValueError, match='Invalid dotenv syntax'):
        render('KEY="unterminated', '', tmp_path / 'tft-chat/.env')


def test_absent_files_are_noop(tmp_path: Path) -> None:
    """Do not create empty application files when no defaults exist."""
    sync(tmp_path)
    assert not list(tmp_path.iterdir())


def test_manual_whitespace_survives_refresh() -> None:
    """Preserve manual comments, blank lines, and CRLF line endings."""
    manual = '# Local\r\nKEY=local\r\n\r\n'
    path = Path('/suite/tft-chat/.env')
    generated = render('SHARED=one\n', manual, path)
    assert render('', generated, path) == manual
    assert render('SHARED=one\n', generated, path) == generated
