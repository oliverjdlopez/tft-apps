"""Independent wisp analysis: bounded frame batches and database-paged detections."""
import json
import uuid
from contextlib import closing
from fastapi import HTTPException
try:
    from . import db, frame_cache
    from .processor import _FrameCropConverter
    from .sampling import TimeSampler
except ImportError:
    import db
    import frame_cache
    from processor import _FrameCropConverter
    from sampling import TimeSampler
from wisp_classifier.detector import TemplateMatcher
from wisp_classifier.ocr import recognize_batch

PAGE_SIZE = 25


def initialize():
    with closing(db.get_db()) as conn, conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS wisp_settings(video_id TEXT PRIMARY KEY, box TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS wisp_jobs(id TEXT PRIMARY KEY, video_id TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS wisp_jobs_video ON wisp_jobs(video_id);
        CREATE TABLE IF NOT EXISTS wisp_hits(job_id TEXT NOT NULL, frame_index INTEGER NOT NULL,
            timestamp REAL NOT NULL, confidence REAL NOT NULL, PRIMARY KEY(job_id, frame_index));
        CREATE TABLE IF NOT EXISTS wisp_scores(job_id TEXT NOT NULL, sample_index INTEGER NOT NULL,
            frame_index INTEGER NOT NULL, timestamp REAL NOT NULL, confidence REAL NOT NULL,
            PRIMARY KEY(job_id, sample_index));
        CREATE INDEX IF NOT EXISTS wisp_scores_time ON wisp_scores(job_id, timestamp);
        """)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(wisp_scores)')}
        if 'ocr_text' not in columns:
            conn.execute('ALTER TABLE wisp_scores ADD COLUMN ocr_text TEXT')
        for row in conn.execute("SELECT * FROM wisp_jobs").fetchall():
            job = json.loads(row['payload'])
            if job['status'] in ('queued', 'running'):
                job.update(status='failed', phase='failed', error='Interrupted by server restart; retry this analysis.')
                conn.execute('UPDATE wisp_jobs SET payload=? WHERE id=?', (json.dumps(job), row['id']))


def get_video(video_id):
    # Avoid loading unrelated round results into this workspace.
    with closing(db.get_db()) as conn:
        row = conn.execute('SELECT * FROM videos WHERE id=?', (video_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Video not found')
        video = {key: row[key] for key in ('id', 'original_name', 'mime_type', 'duration', 'width', 'height', 'created_at')}
        settings = conn.execute('SELECT box FROM wisp_settings WHERE video_id=?', (video_id,)).fetchone()
        jobs = [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM wisp_jobs WHERE video_id=? ORDER BY rowid DESC', (video_id,))]
    video.update(box=json.loads(settings['box']) if settings else None,
                 latest_job=jobs[0] if jobs else None,
                 active_job=next((j for j in jobs if j['status'] in ('queued', 'running')), None),
                 current_job=next((j for j in jobs if j['status'] == 'completed'), None))
    return video


def save_box(video_id, box):
    video = get_video(video_id)
    if box['frame_time'] > video['duration']:
        raise HTTPException(400, 'Box timestamp is outside the video')
    with closing(db.get_db()) as conn, conn:
        conn.execute('INSERT OR REPLACE INTO wisp_settings VALUES (?,?)', (video_id, json.dumps(box)))
    return get_video(video_id)


def create_job(video_id, sample_interval_seconds=0):
    video = get_video(video_id)
    if video['active_job']:
        return video['active_job'], False
    if not video['box']:
        raise HTTPException(400, 'Save a bounding box before processing')
    job = dict(id=uuid.uuid4().hex, status='queued', phase='queued', progress=0, total_samples=0,
               collected_samples=0, batch_size=64, sample_interval_seconds=sample_interval_seconds, reuse_cached_crops=False,
               source_job_id=None, max_timing_error_ms=0, device=None, error=None,
               created_at=db.utc_now(), updated_at=db.utc_now(), results=[], detection_count=0,
               box=video['box'])
    with closing(db.get_db()) as conn, conn:
        conn.execute('INSERT INTO wisp_jobs VALUES (?,?,?)', (job['id'], video_id, json.dumps(job)))
    return job, True


def detections(video_id, job_id, page):
    with closing(db.get_db()) as conn:
        row = conn.execute('SELECT payload FROM wisp_jobs WHERE id=? AND video_id=?', (job_id, video_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Wisp analysis not found')
        job = json.loads(row['payload'])
        if job['status'] != 'completed':
            raise HTTPException(409, 'Analysis is not complete')
        total = job['detection_count']
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages)
        rows = conn.execute('SELECT * FROM wisp_hits WHERE job_id=? ORDER BY frame_index LIMIT ? OFFSET ?',
                            (job_id, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
    return dict(page=page, pages=pages, total=total, results=[dict(frame_index=r['frame_index'],
                timestamp_seconds=r['timestamp'], confidence=r['confidence']) for r in rows])


def review_frame(video_id, job_id, timestamp, offset):
    with closing(db.get_db()) as conn:
        row = conn.execute('SELECT payload FROM wisp_jobs WHERE id=? AND video_id=?', (job_id, video_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Wisp analysis not found')
        if json.loads(row['payload'])['status'] != 'completed':
            raise HTTPException(409, 'Analysis is not complete')
        before = conn.execute('SELECT * FROM wisp_scores WHERE job_id=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1', (job_id, timestamp)).fetchone()
        after = conn.execute('SELECT * FROM wisp_scores WHERE job_id=? AND timestamp>? ORDER BY timestamp LIMIT 1', (job_id, timestamp)).fetchone()
        candidates = [r for r in (before, after) if r is not None]
        if not candidates:
            raise HTTPException(409, 'Rerun analysis to save confidence scores for every frame.')
        nearest = min(candidates, key=lambda r: abs(r['timestamp'] - timestamp))
        total = conn.execute('SELECT MAX(sample_index)+1 FROM wisp_scores WHERE job_id=?', (job_id,)).fetchone()[0]
        index = max(0, min(total - 1, nearest['sample_index'] + offset))
        result = dict(conn.execute('SELECT * FROM wisp_scores WHERE job_id=? AND sample_index=?', (job_id, index)).fetchone())
        result['total'] = total
        return result


def run_job(video_id, job_id):
    with closing(db.get_db()) as conn:
        job = json.loads(conn.execute('SELECT payload FROM wisp_jobs WHERE id=?', (job_id,)).fetchone()['payload'])
    pending = []
    scores = []
    def flush():
        job['updated_at'] = db.utc_now()
        with closing(db.get_db()) as conn, conn:
            conn.executemany('INSERT INTO wisp_hits VALUES (?,?,?,?)', pending)
            conn.executemany('INSERT INTO wisp_scores (job_id, sample_index, frame_index, timestamp, confidence, ocr_text) VALUES (?,?,?,?,?,?)', scores)
            conn.execute('UPDATE wisp_jobs SET payload=? WHERE id=?', (json.dumps(job), job_id))
        pending.clear()
        scores.clear()
    try:
        import av
        matcher = TemplateMatcher()
        job.update(status='running', phase='preparing', device=matcher.device_label)
        flush()
        def prepare_progress(processed, total):
            job.update(collected_samples=processed, total_samples=total)
            flush()
        shared_frames = frame_cache.ensure(db.video_path(video_id), prepare_progress,
                                           sample_interval_seconds=job["sample_interval_seconds"])
        job.update(phase='processing', collected_samples=0, progress=0)
        flush()
        with shared_frames.open() as container:
            stream = container.streams.video[0]
            stream.thread_type = 'AUTO'
            sampler = TimeSampler(job['sample_interval_seconds'])
            converter = _FrameCropConverter(av, job['box'])
            selected = 0
            origin = float((stream.start_time or 0) * stream.time_base)
            job['total_samples'] = stream.frames or max(1, round(get_video(video_id)['duration'] * float(stream.average_rate or 30)))
            if job['sample_interval_seconds'] > 0:
                import math
                job['total_samples'] = math.ceil(get_video(video_id)['duration'] / job['sample_interval_seconds'])
            batch = []
            batch_bytes = 0
            def classify_batch():
                nonlocal batch_bytes
                if not batch:
                    return
                predictions = matcher.predict_batch([crop for _, _, crop in batch])
                texts = recognize_batch([crop for _, _, crop in batch])
                from wisp_classifier.ocr import runtime_status
                job['ocr_devices'] = runtime_status()
                for (frame_index, timestamp, _), (detected, confidence), text in zip(batch, predictions, texts, strict=True):
                    scores.append((job_id, job['progress'] + len(scores), frame_index, timestamp, confidence, text))
                    if detected:
                        pending.append((job_id, frame_index, timestamp, confidence))
                        job['detection_count'] += 1
                job['progress'] += len(batch)
                flush()
                batch.clear()
                batch_bytes = 0

            for index, frame in enumerate(container.decode(stream)):
                index = getattr(frame, "index", index)
                if frame.pts is None or frame.time_base is None:
                    raise RuntimeError('A video frame has no presentation timestamp')
                timestamp = float(frame.pts * frame.time_base) - origin
                if not sampler.select(timestamp):
                    continue
                selected += 1
                crop, _ = converter.convert(frame)
                if batch and (batch_bytes + crop.nbytes > 32 * 1024 * 1024 or batch[0][2].shape != crop.shape):
                    classify_batch()
                batch.append((index, timestamp, crop))
                batch_bytes += crop.nbytes
                job['collected_samples'] = selected
                job['total_samples'] = max(job['total_samples'], selected)
                if len(batch) >= job['batch_size']:
                    classify_batch()
            classify_batch()
        job.update(status='completed', phase='completed', total_samples=job['progress'])
        flush()
    except Exception as exc:
        job.update(status='failed', phase='failed', error=str(exc))
        flush()
