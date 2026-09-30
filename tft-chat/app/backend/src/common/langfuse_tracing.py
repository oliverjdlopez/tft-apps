"""Optional Langfuse export of real Agents SDK operations and prompt lineage."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import logging
import threading

logger = logging.getLogger(__name__)
PROMPTS = ContextVar('langfuse_frozen_prompts', default={})
ACTIVE = ContextVar('langfuse_tracing_active', default=False)
_INITIALIZE_LOCK = threading.Lock()
_CLIENT = None


class ScopedSampler:
    """Record only explicitly opted-in conversations and propagated eval workers."""

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None, trace_state=None):
        """Keep disabled requests out of the exporter even after earlier opt-in use."""
        from opentelemetry.sdk.trace.sampling import SamplingResult, Decision
        return SamplingResult(Decision.RECORD_AND_SAMPLE if ACTIVE.get() else Decision.DROP,
                              attributes=attributes, trace_state=trace_state)

    def get_description(self):
        """Describe the process-local explicit tracing policy."""
        return 'ChatTFT explicit tracing scope'


class PromptLineageProcessor:
    """Associate generations with the frozen prompt of their owning agent."""

    def __init__(self):
        """Keep lineage scoped to OpenTelemetry span identities across concurrent runs."""
        self.owners = {}
        self.lock = threading.Lock()

    def on_start(self, span, parent_context=None):
        """Inherit the owning agent through parent spans before generation export."""
        prompts = PROMPTS.get()
        key = (span.context.trace_id, span.context.span_id)
        parent = (span.context.trace_id, span.parent.span_id) if span.parent else None
        with self.lock:
            owner = span.name if span.name in prompts else self.owners.get(parent)
            self.owners[key] = owner
        if (span.attributes or {}).get('openinference.span.kind') == 'LLM' and owner:
            prompt = prompts[owner]
            reference = prompt.get('native_reference', prompt)
            if reference:
                span.set_attribute('langfuse.prompt.name', reference['name'])
                span.set_attribute('langfuse.prompt.version', reference['version'])
                span.set_attribute('chattft.assistant', owner)

    def _on_ending(self, span):
        """Honor the OpenTelemetry 1.44 processor hook without changing span data."""
        return None

    def on_end(self, span):
        """Release finished lineage entries; parents outlive their child calls."""
        with self.lock:
            self.owners.pop((span.context.trace_id, span.context.span_id), None)

    def shutdown(self):
        """Release process-local lineage when the exporter shuts down."""
        with self.lock:
            self.owners.clear()

    def force_flush(self, timeout_millis=30000):
        """Report immediate completion because this processor buffers no exports."""
        return True


def initialize_tracing(*, exclusive_processor: bool = False):
    """Install instrumentation, retaining app processors outside isolated eval workers."""
    global _CLIENT
    with _INITIALIZE_LOCK:
        if _CLIENT is None:
            from langfuse import Langfuse
            from opentelemetry.sdk.trace import TracerProvider
            from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
            provider = TracerProvider(sampler=ScopedSampler())
            provider.add_span_processor(PromptLineageProcessor())
            client = Langfuse(tracer_provider=provider)
            OpenAIAgentsInstrumentor().instrument(tracer_provider=provider, exclusive_processor=exclusive_processor)
            _CLIENT = client
    return _CLIENT


@contextmanager
def worker_trace(carrier: dict | None, prompts: dict):
    """Attach the experiment's propagated parent before entering a worker graph."""
    if not carrier:
        yield
        return
    from opentelemetry import context, propagate
    client = initialize_tracing(exclusive_processor=True)
    parent = context.attach(propagate.extract(carrier))
    token = PROMPTS.set(prompts)
    active_token = ACTIVE.set(True)
    try:
        yield
    finally:
        PROMPTS.reset(token)
        ACTIVE.reset(active_token)
        context.detach(parent)
        client.flush()


@contextmanager
def development_trace(messages: list[dict], *, enabled: bool):
    """Export opt-in replayable conversation roots without making chat depend on it."""
    if not enabled:
        yield None
        return
    manager = None
    active_token = ACTIVE.set(True)
    try:
        client = initialize_tracing()
        from langfuse import propagate_attributes
        manager = ExitStack()
        manager.enter_context(propagate_attributes(environment='development'))
        observation = manager.enter_context(client.start_as_current_observation(
            name='chattft-development-chat', as_type='span',
            input={'messages': messages}, metadata={'source': 'development'}))
    except Exception:
        logger.warning('Optional Langfuse development tracing is unavailable')
        if manager is not None:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                pass
        manager = None
        observation = None
    try:
        yield observation
    finally:
        if manager is not None:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                logger.warning('Optional Langfuse trace export failed')
        ACTIVE.reset(active_token)
