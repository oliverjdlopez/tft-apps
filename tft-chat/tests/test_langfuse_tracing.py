"""Optional tracing isolation and per-agent prompt lineage without network calls."""
from types import SimpleNamespace

from common import langfuse_tracing as tracing
from domain.assistants.constants import AssistantName


def test_disabled_development_tracing_never_initializes(monkeypatch):
    """Keep the default chat path independent of optional dependencies/exporters."""
    def unavailable():
        """Fail if disabled tracing accidentally accesses its exporter."""
        raise AssertionError('Tracing must remain disabled')
    monkeypatch.setattr(tracing, 'initialize_tracing', unavailable)
    with tracing.development_trace([{'role': 'user', 'content': 'hello'}], enabled=False) as span:
        assert span is None


def test_missing_exporter_never_fails_conversation(monkeypatch):
    """An unavailable optional tracing dependency does not suppress chat output."""
    def unavailable():
        """Model a missing optional dependency."""
        raise ImportError('optional tracing unavailable')
    monkeypatch.setattr(tracing, 'initialize_tracing', unavailable)
    with tracing.development_trace([], enabled=True) as span:
        assert span is None


class Span:
    """Represent mutable OpenTelemetry span attributes for isolated lineage tests."""

    def __init__(self, trace_id, span_id, parent_id, name, kind):
        """Create a span with explicit ownership and scope."""
        self.context = SimpleNamespace(trace_id=trace_id, span_id=span_id)
        self.parent = SimpleNamespace(span_id=parent_id) if parent_id else None
        self.name = name
        self.attributes = {'openinference.span.kind': kind}

    def set_attribute(self, name, value):
        """Apply instrumentation attributes as the SDK would."""
        self.attributes[name] = value


def test_generation_prompt_ownership_and_concurrency():
    """Handoffs and concurrent traces never inherit another agent's prompt."""
    processor = tracing.PromptLineageProcessor()
    token = tracing.PROMPTS.set({AssistantName.CHAT: {'name': 'chat-prompt', 'version': 2},
                                AssistantName.FINAL_RESPONDER: {'name': 'final-prompt', 'version': 4}})
    try:
        chat = Span(1, 1, None, AssistantName.CHAT, 'AGENT')
        responder = Span(1, 2, 1, AssistantName.FINAL_RESPONDER, 'AGENT')
        other = Span(2, 2, None, AssistantName.CHAT, 'AGENT')
        for span in [chat, responder, other]:
            processor.on_start(span)
        output = Span(1, 3, 2, 'response', 'LLM')
        concurrent = Span(2, 3, 2, 'response', 'LLM')
        processor.on_start(output)
        processor.on_start(concurrent)
        assert output.attributes['langfuse.prompt.name'] == 'final-prompt'
        assert output.attributes['langfuse.prompt.version'] == 4
        assert concurrent.attributes['langfuse.prompt.name'] == 'chat-prompt'
        for span in [output, concurrent, chat, responder, other]:
            processor._on_ending(span)
            processor.on_end(span)
        assert not processor.owners
    finally:
        tracing.PROMPTS.reset(token)


def test_documented_instrumentation_records_sdk_operations_in_scope():
    """Exercise real agent/tool/handoff spans and suppress later disabled requests."""
    import subprocess
    import sys
    import pytest
    pytest.importorskip('langfuse')
    pytest.importorskip('openinference.instrumentation.openai_agents')
    script = '''
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from agents import trace, agent_span, generation_span, function_span, handoff_span
from common.langfuse_tracing import ScopedSampler, PromptLineageProcessor, PROMPTS, ACTIVE
from domain.assistants.constants import AssistantName
provider = TracerProvider(sampler=ScopedSampler())
exporter = InMemorySpanExporter()
provider.add_span_processor(PromptLineageProcessor())
provider.add_span_processor(SimpleSpanProcessor(exporter))
OpenAIAgentsInstrumentor().instrument(tracer_provider=provider, exclusive_processor=False)
active = ACTIVE.set(True)
prompts = PROMPTS.set({AssistantName.CHAT: {'name': 'chat', 'version': 2}, AssistantName.FINAL_RESPONDER: {'name': 'final', 'version': 3}})
with provider.get_tracer('test').start_as_current_span('experiment-parent'):
    with trace('application'):
        with agent_span(AssistantName.CHAT):
            with generation_span(model='mock', usage={'input_tokens': 10, 'output_tokens': 2}): pass
            with handoff_span(from_agent=AssistantName.CHAT, to_agent=AssistantName.FINAL_RESPONDER): pass
        with agent_span(AssistantName.FINAL_RESPONDER):
            with generation_span(model='mock', usage={'input_tokens': 20, 'output_tokens': 4}): pass
            with function_span('present_inline_data', input='{"rows":[1,2]}', output='displayed'): pass
PROMPTS.reset(prompts)
ACTIVE.reset(active)
spans = exporter.get_finished_spans()
assert len({span.context.trace_id for span in spans}) == 1
llms = [span for span in spans if span.attributes.get('openinference.span.kind') == 'LLM']
assert [(span.attributes['langfuse.prompt.name'], span.attributes['langfuse.prompt.version']) for span in llms] == [('chat',2),('final',3)]
assert [span.attributes['llm.token_count.prompt'] for span in llms] == [10,20]
assert any(span.name == f'handoff to {AssistantName.FINAL_RESPONDER}' for span in spans)
assert any(span.name == 'present_inline_data' and 'rows' in span.attributes['input.value'] for span in spans)
count = len(spans)
with trace('disabled-conversation'):
    with agent_span(AssistantName.CHAT): pass
assert len(exporter.get_finished_spans()) == count
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_development_tracing_requires_explicit_typed_opt_in(tmp_path):
    """INI configuration defaults off and accepts an explicit Boolean opt-in."""
    from core.config import load_config
    path = tmp_path / 'chat.ini'
    path.write_text('[chat]\n')
    assert load_config(path).chat.langfuse_tracing is False
    path.write_text('[chat]\nlangfuse_tracing = true\n')
    assert load_config(path).chat.langfuse_tracing is True
