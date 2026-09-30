import json

from backend import db, wisps
from wisp_classifier import ocr


def test_raw_text_is_preserved_without_label_filtering(monkeypatch):
    monkeypatch.setattr(ocr.sys, 'platform', 'linux')
    import numpy as np
    from types import SimpleNamespace
    crops = [np.zeros((8, 16, 3), dtype=np.uint8)] * 2
    def recognize(images):
        assert images is crops
        return [
            SimpleNamespace(json={'res': {'rec_text': '  Hello 42! ', 'rec_score': 0.01}}),
            SimpleNamespace(json={'res': {'rec_text': ''}}),
        ]
    monkeypatch.setattr(ocr, 'recognize_images', recognize)
    assert ocr.recognize_batch(crops) == ['  Hello 42! ', '']


def test_migration_and_frame_review_preserve_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'test.sqlite3')
    with db.get_db() as conn:
        conn.execute('CREATE TABLE wisp_scores(job_id TEXT, sample_index INTEGER, frame_index INTEGER, timestamp REAL, confidence REAL, PRIMARY KEY(job_id, sample_index))')
        conn.execute('INSERT INTO wisp_scores VALUES (?,?,?,?,?)', ('job', 0, 0, 0, 0.9))
    wisps.initialize()
    wisps.initialize()
    with db.get_db() as conn:
        conn.execute('INSERT INTO wisp_jobs VALUES (?,?,?)', ('job', 'video', json.dumps({'status': 'completed'})))
        conn.execute('INSERT INTO wisp_scores VALUES (?,?,?,?,?,?)', ('job', 1, 1, 0.04, 0.1, 'raw text'))
        conn.execute('INSERT INTO wisp_scores VALUES (?,?,?,?,?,?)', ('job', 2, 2, 0.08, 0.2, ''))
    assert wisps.review_frame('video', 'job', 0, 0)['ocr_text'] is None
    assert wisps.review_frame('video', 'job', 0, 1)['ocr_text'] == 'raw text'
    assert wisps.review_frame('video', 'job', 0.04, 1)['ocr_text'] == ''
