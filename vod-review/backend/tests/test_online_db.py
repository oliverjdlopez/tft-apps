"""Persistence guarantees for remote reviews and local conversion."""
import sqlite3
from pathlib import Path
import pytest
from fastapi import HTTPException
from backend import db
from backend.models import OnlineVideoRequest, ProcessingRequest, VideoModeRequest


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """Configure an isolated temporary application database."""
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(db, 'VIDEO_DIR', tmp_path / 'videos')
    monkeypatch.setattr(db, 'DOWNLOAD_DIR', tmp_path / 'downloads')
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'vod.sqlite3')
    return tmp_path


def review():
    """Create a ten-minute review within a longer source."""
    return db.create_online_video('remote', {'source_id': 'abcdefghijk', 'source_url': 'https://www.youtube.com/watch?v=abcdefghijk', 'original_name': 'Tournament', 'duration': 1800, 'width': 1280, 'height': 720}, 300, 900)


def box():
    """Return a normalized test crop."""
    return {'x': .5, 'y': 0, 'width': .2, 'height': .1, 'frame_time': 5}


def test_implicit_source_end_is_frozen_and_conversion_is_recoverable_without_checkpoints(isolated_db):
    """An open-ended import retains its original coverage and tracked conversion."""
    db.init_db()
    video = db.create_online_video('remote', {'source_id': 'abcdefghijk', 'source_url': 'https://www.youtube.com/watch?v=abcdefghijk', 'original_name': 'Tournament', 'duration': 1800, 'width': 1280, 'height': 720}, 300)
    assert video['duration'] == 1500 and video['source_end_seconds'] == 1800
    db.create_download_task('conversion', url=video['source_url'], target_video_id=video['id'])
    task = db.get_resumable_download_task()
    assert task['task_id'] == 'conversion' and task['target_video_id'] == video['id']


def test_conversion_preserves_identity_crop_duration_results(isolated_db):
    db.init_db()
    video = review()
    assert video['duration'] == 600 and video['source_start_seconds'] == 300
    assert video['mode'] == 'online' and not video['local_available'] and 'path' not in video
    assert db.physical_video_path('remote') is None
    with pytest.raises(HTTPException) as error:
        db.video_path('remote')
    assert error.value.status_code == 409
    db.save_bounding_box('remote', box())
    job, created = db.create_processing_job('remote', 'first', 64, 10)
    assert created and job['strategy'] == 'online' and job['refinement_interval_seconds'] == 1
    db.complete_job('first', 'remote', [(0, .01, '11', .9)], 1, 1, 'cpu')
    local = isolated_db / 'local.mp4'
    local.write_bytes(b'fixture')
    bound = db.bind_local_copy('remote', local, 'video/mp4', 1920, 1080)
    assert bound['id'] == 'remote' and bound['duration'] == 600 and bound['box'] == box()
    assert bound['current_job']['id'] == 'first'
    assert bound['mode'] == 'online' and bound['local_available']
    assert db.set_video_mode('remote', 'offline')['mode'] == 'offline'
    assert db.video_path('remote') == local
    assert db.set_video_mode('remote', 'online')['local_available']
    with pytest.raises(HTTPException):
        db.video_path('remote')
    assert db.physical_video_path('remote') == local
    assert db.set_video_mode('remote', 'offline')['mode'] == 'offline'


def test_progressive_results_do_not_replace_completed_result_on_failure(isolated_db):
    db.init_db()
    review()
    db.save_bounding_box('remote', box())
    db.create_processing_job('remote', 'first', 64, 10)
    db.complete_job('first', 'remote', [(0, 0, '11', .9)], 1, 1, 'cpu')
    db.create_processing_job('remote', 'second', 64, 10)
    results = [(0, 0, '11', .9), (10, 10.1, '12', .8)]
    db.store_partial_results('second', results[:1])
    db.store_partial_results('second', results)
    video = db.get_video('remote')
    assert len(video['active_job']['results']) == 2 and video['current_job']['id'] == 'first'
    with pytest.raises(HTTPException) as error:
        db.set_video_mode('remote', 'online')
    assert error.value.status_code == 409
    db.complete_job('second', 'remote', results, 2, 2, 'cpu')
    assert len(db.get_video('remote')['current_job']['results']) == 2
    db.create_processing_job('remote', 'third', 64, 10)
    db.store_partial_results('third', results[:1])
    db.fail_job('third', 'network failure')
    assert db.get_video('remote')['current_job']['id'] == 'second'


def test_remote_deletion_and_conversion_target(isolated_db):
    db.init_db()
    review()
    db.create_download_task('conversion', url='https://youtu.be/abcdefghijk', target_video_id='remote')
    assert db.get_download_request('conversion')['target_video_id'] == 'remote'
    assert db.get_download_task('conversion')['target_video_id'] == 'remote'
    assert db.delete_video('remote') is None


def test_legacy_migration_preserves_schema_custom_objects_and_foreign_keys(isolated_db):
    connection = sqlite3.connect(db.DB_PATH)
    connection.executescript('''
        CREATE TABLE videos (id TEXT PRIMARY KEY, original_name TEXT NOT NULL, path TEXT NOT NULL,
            mime_type TEXT NOT NULL, duration REAL NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            created_at TEXT NOT NULL, box_x REAL, box_y REAL, box_width REAL, box_height REAL,
            box_frame_time REAL, current_job_id TEXT, custom_owner TEXT DEFAULT 'preserved');
        CREATE INDEX custom_video_name ON videos(original_name);
        CREATE VIEW custom_video_view AS SELECT id, original_name FROM videos;
        CREATE TABLE authored_notes (video_id TEXT REFERENCES videos(id), note TEXT);
        CREATE TABLE audit (event TEXT);
        CREATE TRIGGER custom_audit AFTER UPDATE ON videos BEGIN INSERT INTO audit VALUES('updated'); END;
        INSERT INTO videos(id,original_name,path,mime_type,duration,width,height,created_at)
            VALUES('legacy','Uploaded','/old/video.mp4','video/mp4',20,640,480,'2020-01-01');
        INSERT INTO authored_notes VALUES('legacy','Keep me');
    ''')
    connection.close()
    db.init_db()
    db.init_db()
    connection = db.get_db()
    try:
        row = connection.execute('SELECT * FROM videos WHERE id="legacy"').fetchone()
        assert connection.execute('SELECT id FROM custom_video_view').fetchone()[0] == 'legacy'
        assert row['custom_owner'] == 'preserved' and row['path'] == '/old/video.mp4'
        assert row['mode'] == 'offline' and row['source_id'] is None
        assert connection.execute('SELECT note FROM authored_notes').fetchone()[0] == 'Keep me'
        assert connection.execute('PRAGMA foreign_key_list(authored_notes)').fetchone()['table'] == 'videos'
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        assert connection.execute('SELECT name FROM sqlite_master WHERE name="custom_video_name"').fetchone()
        assert connection.execute('SELECT name FROM sqlite_master WHERE name="custom_audit"').fetchone()
        assert not next(row for row in connection.execute('PRAGMA table_info(videos)') if row['name'] == 'path')['notnull']
    finally:
        connection.close()
    review()


def test_recovery_only_from_completed_supported_download(isolated_db):
    db.init_db()
    for identifier in ('youtube', 'upload', 'failed', 'twitch'):
        db.create_video(identifier, identifier, Path('/not/present.mp4'), 'video/mp4', 300, 1280, 720)
    for identifier, url, status in [('youtube', 'https://youtu.be/abcdefghijk', 'completed'), ('failed', 'https://youtu.be/abcdefghijk', 'failed'), ('twitch', 'https://www.twitch.tv/videos/123', 'completed')]:
        db.create_download_task(identifier, url=url, start_seconds=60, end_seconds=360)
        db.update_download_task(identifier, status=status, video_id=identifier)
    db.init_db()
    video = db.get_video('youtube')
    assert video['source_id'] == 'abcdefghijk' and video['source_start_seconds'] == 60 and video['source_end_seconds'] == 360
    for identifier in ('upload', 'failed', 'twitch'):
        assert db.get_video(identifier)['source_id'] is None


def test_request_defaults_and_validation():
    assert ProcessingRequest().sample_interval_seconds is None
    assert OnlineVideoRequest(url='https://youtu.be/abcdefghijk').quality == '720p'
    with pytest.raises(ValueError):
        OnlineVideoRequest(url='https://youtu.be/abcdefghijk', start_seconds=10, end_seconds=5)
    with pytest.raises(ValueError):
        VideoModeRequest(mode='invalid')


def test_path_migration_rolls_back_as_one_transaction():
    """An interrupted table replacement retains the complete original table."""
    class FailingRenameConnection(sqlite3.Connection):
        """Inject a failure after the old table has been dropped."""

        def execute(self, sql, parameters=()):
            if sql == 'ALTER TABLE videos_nullable_migration RENAME TO videos':
                raise sqlite3.OperationalError('Injected migration failure')
            return super().execute(sql, parameters)

    connection = sqlite3.connect(':memory:', factory=FailingRenameConnection)
    connection.row_factory = sqlite3.Row
    connection.executescript("CREATE TABLE videos(id TEXT PRIMARY KEY,path TEXT NOT NULL); INSERT INTO videos VALUES('saved','/saved.mp4');")
    with pytest.raises(sqlite3.OperationalError, match='Injected'):
        db._migrate_nullable_video_path(connection)
    assert connection.execute('SELECT path FROM videos WHERE id="saved"').fetchone()[0] == '/saved.mp4'
    assert not connection.execute("SELECT name FROM sqlite_master WHERE name='videos_nullable_migration'").fetchall()
    assert connection.execute('PRAGMA legacy_alter_table').fetchone()[0] == 0
    connection.close()
