"""Verify completed subprocess spans survive a forced application timeout in CI."""
from functools import partial
import os
from pathlib import Path
import time

from langfuse import Langfuse

from evals.langfuse.content import load_catalog, load_snapshot
from evals.langfuse.experiments import run_item_task
from evals.langfuse.utils import configured_workspace, atomic_write, canonical_json
from domain.assistants.constants import AssistantName


def main():
    """Run a real handoff followed by a delayed local mock response and termination."""
    if os.environ.get('LANGFUSE_TEST_DEPLOYMENT') != '1' or 'mock-model:8000' not in os.environ.get('OPENAI_BASE_URL', ''):
        raise RuntimeError('Timeout acceptance requires an isolated mock deployment')
    os.environ['EVAL_OPERATION_TIMEOUT_SECONDS'] = '8'
    root = Path('evals/langfuse/snapshots')
    entry = next(row for row in load_catalog(root) if row['name'] == AssistantName.CHAT)
    bundle = load_snapshot(entry['snapshot'], root)
    client = Langfuse()
    workspace = configured_workspace()
    dataset = client.get_dataset('end-to-end')
    item = dataset.items[0].model_copy(update={
        'input': 'TRACE_TIMEOUT_TEST: please say hello.',
        'metadata': {'case_id': 'timeout-smoke', 'quality_profile': None}})
    results = {}
    try:
        name = 'timeout evidence ' + str(time.time())
        run = client.run_experiment(name=name, run_name=name, data=[item], task=partial(
            run_item_task, suite=bundle['suite'], variant={'name': 'timeout', 'model': 'mock-judge'},
            prompts=bundle['prompts'], client=client, result_store=results))
        assert 'exceeded 8 seconds' in results['timeout-smoke']['error'], results
        client.flush()
        trace_id = run.item_results[0].trace_id
        deadline = time.time() + 90
        while time.time() < deadline:
            spans = workspace.list('v2/observations', cursor=True, traceId=trace_id,
                                   fields='core,basic,time,usage,prompt')
            completed = [span for span in spans if span['type'] == 'GENERATION' and span.get('endTime')]
            if (completed and any('handoff' in span['name'] for span in spans)
                    and any(span['name'] == 'experiment-item-task' and span['level'] == 'ERROR' for span in spans)):
                assert any(span.get('totalUsage') == 15 for span in completed), completed
                assert any(span.get('promptName') == f"chattft/assistants/{AssistantName.CHAT}" for span in completed), completed
                atomic_write(Path('/tmp/chattft-timeout-trace.json'), canonical_json(spans))
                print('Timeout retained completed generation usage, owning prompt, handoff, and root execution error.')
                return
            time.sleep(2)
        raise AssertionError('Completed timeout evidence did not persist')
    finally:
        workspace.close()
        client.shutdown()


if __name__ == '__main__':
    main()
