"""Records every LLM and tool call the swarm makes into the partner ledger."""

from crewai.events import (
    BaseEventListener,
    LLMCallCompletedEvent,
    LLMCallFailedEvent,
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
)

from halloween_swarm.partners import LEDGER


class EvidenceListener(BaseEventListener):
    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(LLMCallCompletedEvent)
        def on_llm(source, event):
            usage = event.usage or {}
            LEDGER.add("parasail", f"chat:{event.model}", agent=(getattr(event, "agent_role", None) or "").strip() or None, ok=True,
                       tokens=usage.get("total_tokens"))

        @crewai_event_bus.on(LLMCallFailedEvent)
        def on_llm_failed(source, event):
            LEDGER.add("parasail", f"chat:{event.model}", agent=(getattr(event, "agent_role", None) or "").strip() or None, ok=False,
                       error=event.error[:160])

        @crewai_event_bus.on(ToolUsageFinishedEvent)
        def on_tool(source, event):
            LEDGER.add("crewai", f"tool:{event.tool_name}", agent=(event.agent_role or "").strip(), ok=True)

        @crewai_event_bus.on(ToolUsageErrorEvent)
        def on_tool_error(source, event):
            LEDGER.add("crewai", f"tool:{event.tool_name}", agent=(event.agent_role or "").strip(), ok=False, error=str(event.error)[:160])


EVIDENCE_LISTENER = EvidenceListener()
