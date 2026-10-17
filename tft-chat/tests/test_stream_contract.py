"""Exercise Python-produced events through the real JavaScript stream parser."""

import json
from pathlib import Path
import subprocess

from services.streaming import STREAM_EVENT_PREFIX, STREAM_EVENT_SUFFIX, stream_event


def test_python_frames_survive_every_javascript_transport_boundary():
    """Preserve Unicode, event ordering, malformed frames, and incomplete tails."""
    events = [{"type": "tool", "name": "Café ☕ 中文"}, {"type": "text_part_complete"}]
    malformed = STREAM_EVENT_PREFIX + "not-base64" + STREAM_EVENT_SUFFIX
    wire = "Answer 🐉" + "".join(map(stream_event, events)) + malformed + STREAM_EVENT_PREFIX[:8]
    script = """
import assert from 'node:assert/strict';
import { consumeStreamBuffer } from './app/frontend/src/streaming.js';
let input=''; for await (const chunk of process.stdin) input+=chunk;
const {wire,events,malformed,tail}=JSON.parse(input);
for(let width=1;width<=wire.length;width++) {
 let pending='', text='', actual=[];
 for(let offset=0;offset<wire.length;offset+=width) {
  const part=consumeStreamBuffer(pending+wire.slice(offset,offset+width));
  pending=part.pending; text+=part.text; actual.push(...part.events);
 }
 assert.deepEqual(actual,events);
 assert.equal(pending,tail);
 assert.ok(text.includes('Answer 🐉'));
 assert.ok(text.includes(malformed));
}
"""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=root,
                            input=json.dumps({"wire": wire, "events": events, "malformed": malformed,
                                              "tail": STREAM_EVENT_PREFIX[:8]}), text=True,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
