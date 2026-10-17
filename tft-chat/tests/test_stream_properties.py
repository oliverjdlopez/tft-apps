"""Generated cross-language UTF-8 fragmentation through the real stream parser."""

import base64
import json
from pathlib import Path
import subprocess

from hypothesis import example, given, settings, strategies as st

from services.streaming import stream_event


@settings(max_examples=25, deadline=None, derandomize=True)
@example(text="Café ☕ 🐉 中文", widths=[1])
@given(text=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=100),
       widths=st.lists(st.integers(1, 15), min_size=1, max_size=20))
def test_generated_utf8_chunks_preserve_event_payload(text, widths):
    """Split bytes rather than JavaScript characters, including multibyte boundaries."""
    event = {"type": "diagnostic", "text": text}
    data = (text + stream_event(event)).encode()
    script = """
import assert from 'node:assert/strict';
import {consumeStreamBuffer} from './app/frontend/src/streaming.js';
let input='';for await(const chunk of process.stdin)input+=chunk;
const {data,widths,event,plaintext}=JSON.parse(input),bytes=Buffer.from(data,'base64');
const decoder=new TextDecoder();let pending='',events=[],actualText='',offset=0,index=0;
while(offset<bytes.length){const end=Math.min(bytes.length,offset+widths[index++%widths.length]);
const part=consumeStreamBuffer(pending+decoder.decode(bytes.subarray(offset,end),{stream:true}));
pending=part.pending;actualText+=part.text;events.push(...part.events);offset=end;}
const last=consumeStreamBuffer(pending+decoder.decode());events.push(...last.events);
actualText+=last.text;assert.deepEqual(events,[event]);assert.equal(last.pending,'');
assert.ok(actualText.startsWith(plaintext));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                            input=json.dumps({"data": base64.b64encode(data).decode(), "widths": widths, "event": event, "plaintext": text}), timeout=10)
    assert result.returncode == 0, result.stderr
