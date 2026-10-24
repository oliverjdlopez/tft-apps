"""Compare sequential and batched faster-whisper on existing local audio."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import traceback


def save(path, value):
    """Write a JSON artifact atomically."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def sample_memory(stop, samples):
    """Sample this process's NVIDIA memory, where driver reporting supports it."""
    while not stop.is_set():
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-compute-apps=pid,used_gpu_memory',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=2, check=True,
            )
            values = [int(parts[1].strip()) for line in result.stdout.splitlines()
                      if len(parts := line.split(',')) == 2
                      and parts[0].strip() == str(os.getpid())
                      and parts[1].strip().isdigit()]
            if values:
                samples.append(sum(values))
        except (OSError, subprocess.SubprocessError):
            return
        stop.wait(0.5)


def worker(config):
    """Run one isolated trial, consuming the lazy iterator inside the timer.

    Args:
        config: Trial configuration including source and artifact paths.
    """
    destination = Path(config['destination'])
    result = dict(config, status='failed')
    stop = threading.Event()
    samples = []
    sampler = threading.Thread(target=sample_memory, args=(stop, samples), daemon=True)
    sampler.start()
    try:
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        result['versions'] = {name: importlib.metadata.version(name)
                              for name in ('faster-whisper', 'ctranslate2', 'av')}
        started = time.perf_counter()
        model = WhisperModel(config['model'], device='cuda',
                             device_index=config['device_index'], compute_type='float16',
                             local_files_only=not config['allow_download'])
        result['model_load_seconds'] = time.perf_counter() - started
        runner = BatchedInferencePipeline(model=model) if config['batch_size'] else model
        options = dict(beam_size=5, vad_filter=True, without_timestamps=False)
        if config['language']:
            options['language'] = config['language']
        if config['batch_size']:
            options['batch_size'] = config['batch_size']
        result['requested_options'] = options
        started = time.perf_counter()
        segments, info = runner.transcribe(config['audio'], **options)
        result['transcribe_setup_seconds'] = time.perf_counter() - started
        rows = [{'start': segment.start, 'end': segment.end, 'text': segment.text}
                for segment in segments]
        elapsed = time.perf_counter() - started
        result.update(
            status='completed', transcription_seconds=elapsed,
            segment_iteration_seconds=elapsed - result['transcribe_setup_seconds'],
            duration_seconds=info.duration, duration_after_vad_seconds=info.duration_after_vad,
            audio_minutes_per_wall_minute=info.duration / elapsed,
            language=info.language, segment_count=len(rows),
            effective_options=asdict(info.transcription_options),
            vad_options=asdict(info.vad_options) if info.vad_options else None,
        )
        save(destination / 'transcript.json', {
            'time_origin': 'media_start', 'time_unit': 'seconds',
            'language': info.language, 'segments': rows,
        })
        (destination / 'transcript.txt').write_text(''.join(row['text'] for row in rows).strip())
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
        traceback.print_exc()
    finally:
        stop.set()
        sampler.join(timeout=3)
        result['sampled_peak_process_vram_mib'] = max(samples) if samples else None
        save(destination / 'result.json', result)
    return 0 if result['status'] == 'completed' else 1


def positive(value):
    """Parse a positive repeat count."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return number


def main():
    """Run sequential trials and persist their measurements and transcripts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path, nargs='+', help='Existing audio/video files; no downloads')
    parser.add_argument('--model', default='large-v3', help='Cached model name or local CTranslate2 directory')
    parser.add_argument('--language', help='Optional fixed language, e.g. en; default is autodetection')
    parser.add_argument('--device-index', type=int, default=0)
    parser.add_argument('--repeats', type=positive, default=1)
    parser.add_argument('--allow-download', action='store_true', help='Allow downloading missing model weights')
    parser.add_argument('--output', type=Path, help='New results directory (must not exist)')
    args = parser.parse_args()
    sources = [path.expanduser().resolve() for path in args.audio]
    for source in sources:
        if not source.is_file():
            parser.error(f'Not a local file: {source}')
    if args.device_index < 0:
        parser.error('--device-index must be nonnegative')
    output = (args.output or Path(__file__).parent / 'results' /
              datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    trials = []
    for source_index, source in enumerate(sources):
        for repeat in range(args.repeats):
            # Rotate trial order across repeats to reduce cache/order bias.
            batches = [0, 4, 8]
            batches = batches[repeat % 3:] + batches[:repeat % 3]
            for batch in batches:
                label = f'batch-{batch}' if batch else 'baseline'
                destination = output / f'{source_index:02d}-{source.stem}-{repeat + 1}-{label}'
                destination.mkdir()
                config = dict(audio=str(source), source_index=source_index,
                              source_bytes=source.stat().st_size,
                              source_mtime_ns=source.stat().st_mtime_ns,
                              model=args.model, language=args.language, device_index=args.device_index,
                              allow_download=args.allow_download, batch_size=batch,
                              repeat=repeat + 1, destination=str(destination))
                save(destination / 'config.json', config)
                print(f'Starting {source.name}: {label}, repeat {repeat + 1}', flush=True)
                started = time.perf_counter()
                with (destination / 'worker.log').open('w') as log:
                    process = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                              '--worker', str(destination / 'config.json')],
                                             stdout=log, stderr=subprocess.STDOUT)
                result_path = destination / 'result.json'
                result = json.loads(result_path.read_text()) if result_path.exists() else dict(
                    config, status='failed', error=f'Worker exited {process.returncode}; see worker.log')
                result['worker_wall_seconds'] = time.perf_counter() - started
                result['exit_code'] = process.returncode
                if process.returncode:
                    result['status'] = 'failed'
                save(result_path, result)
                trials.append(result)
                save(output / 'results.json', trials)
                if result['status'] == 'completed':
                    print(f"Completed: {result['transcription_seconds']:.1f}s, "
                          f"{result['audio_minutes_per_wall_minute']:.2f}x realtime", flush=True)
                else:
                    print(f"Failed: {result.get('error', 'see worker.log')}", flush=True)
    summary = []
    for source_index, source in enumerate(sources):
        baseline = [row['transcription_seconds'] for row in trials if
                    row['source_index'] == source_index and row['batch_size'] == 0
                    and row['status'] == 'completed']
        for batch in (0, 4, 8):
            times = [row['transcription_seconds'] for row in trials if
                     row['source_index'] == source_index and row['batch_size'] == batch
                     and row['status'] == 'completed']
            median = statistics.median(times) if times else None
            summary.append(dict(audio=str(source), batch_size=batch, successful_trials=len(times),
                                median_transcription_seconds=median,
                                speedup_vs_baseline=statistics.median(baseline) / median
                                if baseline and median else None))
    save(output / 'summary.json', summary)
    print(f'Results: {output}', flush=True)
    return int(any(row['status'] != 'completed' for row in trials))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        sys.exit(worker(json.loads(Path(sys.argv[2]).read_text())))
    sys.exit(main())
