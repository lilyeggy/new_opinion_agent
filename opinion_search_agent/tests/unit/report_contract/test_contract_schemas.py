from opinion_search.report_contract.contracts import (
    ModuleContract,
    ModuleState,
    Presence,
    VisualEncoding,
)


def test_module_contract_keeps_explicit_empty_state() -> None:
    contract = ModuleContract(
        semantic_type="event-summary",
        title="事件总览",
        semantic_domain="overview",
        applies_when="always",
        presence=Presence.REQUIRED,
        visual_encodings=(VisualEncoding.CARDS,),
        empty_state=ModuleState.NOT_FOUND,
    )

    assert contract.semantic_type == "event-summary"
    assert contract.presence is Presence.REQUIRED
    assert contract.empty_state is ModuleState.NOT_FOUND
    assert contract.visual_encodings == (VisualEncoding.CARDS,)
