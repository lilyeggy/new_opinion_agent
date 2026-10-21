from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opinion_search.investigation.context import structured_context
from opinion_search.investigation.service import unbacked_specifics
from opinion_search.models.contracts import ModelClient
from opinion_search.report_contract.narrative import filter_narrative
from opinion_search.report_contract.contracts import (
    CitationRef,
    DataShape,
    ModuleState,
    NarrativeSection,
    PlannedModule,
    PresentationPlan,
    VisualEncoding,
)
from opinion_search.report_contract.registry import registry_by_type

_NUMERIC_RE = re.compile(r"\d")


class PresentationSkillSchema(BaseModel):
    # The planner is a presentation layer: a stray field on one item (the model
    # likes adding "title") must not discard the whole plan, narrative included.
    # Content safety is enforced by the narrative gates, not by the schema.
    model_config = ConfigDict(extra="ignore", frozen=True)


class VisualChoice(PresentationSkillSchema):
    module_id: str
    selected_visual: VisualEncoding
    reason: str
    title: str = ""
    table_columns: tuple[str, ...] = ()


class DynamicItemProposal(PresentationSkillSchema):
    cells: dict[str, str] = Field(default_factory=dict)
    source_finding_ids: tuple[str, ...] = ()


class DynamicModuleProposal(PresentationSkillSchema):
    module_id: str
    semantic_type: str
    title: str
    selected_visual: VisualEncoding
    reason: str
    summary: str = ""
    table_columns: tuple[str, ...] = ()
    items: tuple[DynamicItemProposal, ...] = ()


class VisualPlanOutput(PresentationSkillSchema):
    choices: tuple[VisualChoice, ...] = ()
    dynamic_modules: tuple[DynamicModuleProposal, ...] = ()
    narrative: NarrativeSection | None = None


class NarrativeOnlyOutput(PresentationSkillSchema):
    """Second, smaller call: the summary alone, when the plan call came back empty."""

    narrative: NarrativeSection | None = None


NARRATIVE_INSTRUCTIONS = """You are the OpinionSearch Dossier Narrator.
Write a short, checkable summary of the event from the committed findings you are given.
Return only `narrative`: a `headline` and 1 to 3 `paragraphs`.
Every clause MUST carry `finding_ids` copied from the input; a clause without them is dropped.
Every number and every quoted span in a clause MUST already appear in that finding.
Prefer judgment over retelling. Never write a clause you cannot bind.
"""

PRESENTATION_INSTRUCTIONS = """You are the OpinionSearch Autonomous Dossier Presentation Agent.
You receive already verified ContentDocument modules, module data profiles, and optional committed findings.
Your job is to:
1. Select the best allowed visual encoding for each existing module (`choices`), optionally refining its Chinese `title` and `table_columns` order.
2. When `committed_findings` are provided, you may also propose 1 to 4 event-specific `dynamic_modules` for the central `focus` section (using allowed `semantic_type`s such as `debate-comparison`, `claim-matrix`, `position-matrix`, `response-coverage`, or `actions-taken` and visuals such as `debate_versus`, `comparison_table`, `position_matrix`, `response_scorecard`, or `cards`).
Hard safety boundaries:
- Every item in `dynamic_modules` MUST bind non-empty `source_finding_ids` from `committed_findings`.
- Never invent facts, numbers, dates, percentages, or claims not present in the bound findings.
- Do not choose distribution charts unless the module has items with labels and numeric values.
- Write a concise Chinese reason for each choice.

Narrative layer (`narrative`), optional but preferred when committed findings exist:
- Write a short summary a reader can check: a `headline` plus 1 to 3 `paragraphs`.
- Every clause MUST carry `finding_ids` copied from `committed_findings`; a clause without them is dropped.
- Every number and every quoted span in a clause MUST already appear in the evidence those findings cite.
- Prefer judgment over retelling: say what the event amounts to, then support it clause by clause.
- Never write a clause you cannot bind; an unanswered question stays unanswered.
"""


def _module_data_profile(module: PlannedModule) -> dict[str, Any]:
    keys: list[str] = []
    lengths: list[int] = []
    has_numeric = False
    for item in module.items:
        for k, v in item.items():
            if k.startswith("_"):
                continue
            if k not in keys:
                keys.append(k)
            text = str(v or "")
            lengths.append(len(text))
            if _NUMERIC_RE.search(text):
                has_numeric = True
    avg_chars = int(sum(lengths) / len(lengths)) if lengths else 0
    return {
        "item_count": len(module.items),
        "field_keys": keys,
        "avg_text_chars": avg_chars,
        "has_numeric_values": has_numeric,
    }


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _verify_and_build_dynamic_modules(
    proposals: tuple[DynamicModuleProposal, ...],
    findings_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    citation_labels: dict[str, str],
    citation_refs: dict[str, CitationRef],
    registry: dict[str, Any],
) -> list[PlannedModule]:
    if not proposals or not findings_by_id:
        return []

    built: list[PlannedModule] = []
    for index, prop in enumerate(proposals[:5], 1):
        contract = registry.get(prop.semantic_type)
        if contract is None or prop.selected_visual not in contract.visual_encodings:
            continue
        if prop.selected_visual is VisualEncoding.DISTRIBUTION_CHART:
            continue
        if not prop.items:
            continue

        verified_items: list[dict[str, Any]] = []
        module_eids: list[str] = []
        fallback_notes: list[str] = []

        for item_prop in prop.items:
            valid_fids = [fid for fid in item_prop.source_finding_ids if fid in findings_by_id]
            if not valid_fids:
                continue

            bound_findings = [findings_by_id[fid] for fid in valid_fids]
            item_eids: list[str] = []
            allowed_texts: list[str] = []
            for f in bound_findings:
                allowed_texts.append(str(f.get("text") or ""))
                for eid in f.get("evidence_ids") or ():
                    if eid not in item_eids:
                        item_eids.append(eid)
                    ev = evidence_by_id.get(eid)
                    if ev and ev.get("excerpt"):
                        allowed_texts.append(str(ev["excerpt"]))

            module_eids.extend(item_eids)
            badges = " ".join(f"[{citation_labels[eid]}]" for eid in item_eids if eid in citation_labels)

            raw_cells = {str(k): str(v) for k, v in (item_prop.cells or {}).items() if not str(k).startswith("_")}
            combined_cell_text = " ".join(raw_cells.values())
            finding_proxy = type("_FindingProxy", (), {"text": combined_cell_text})()
            evidence_proxies = [type("_ExcerptProxy", (), {"excerpt": t})() for t in allowed_texts]
            unbacked = unbacked_specifics(finding_proxy, evidence_proxies)

            if unbacked or not raw_cells:
                # Deterministic fallback: never allow unbacked numbers/specifics into cells
                primary = bound_findings[0]
                stakeholder = str(primary.get("stakeholder") or "核查判断")
                verbatim = "；".join(str(f.get("text") or "") for f in bound_findings)
                row: dict[str, Any] = {
                    "主体": stakeholder,
                    "核查判断": f"{verbatim} {badges}".strip(),
                    "证据索引": badges or "—",
                    "title": stakeholder,
                    "summary": f"{verbatim} {badges}".strip(),
                    "_source_finding_ids": valid_fids,
                }
                fallback_notes.append(f"条目引用 {', '.join(valid_fids)} 含未锚定数值，已自动回退为核查原文。")
            else:
                row = dict(raw_cells)
                if badges and "证据索引" not in row:
                    row["证据索引"] = badges
                row["_source_finding_ids"] = valid_fids

            verified_items.append(row)

        if not verified_items:
            continue

        cols = tuple(prop.table_columns)
        if not cols and verified_items:
            cols = tuple(k for k in verified_items[0].keys() if not k.startswith("_"))

        citations = tuple(
            citation_refs[eid]
            for eid in dict.fromkeys(module_eids)
            if eid in citation_refs
        )
        reason = prop.reason
        if fallback_notes:
            reason = f"{reason}（{'；'.join(fallback_notes)}）"

        built.append(
            PlannedModule(
                module_id=prop.module_id or f"dynamic-focus-{index}",
                semantic_type=prop.semantic_type,
                title=prop.title or contract.title,
                state=ModuleState.READY,
                data_shape=DataShape.COMPARISON,
                summary=prop.summary,
                table_columns=cols,
                items=tuple(verified_items),
                citations=citations,
                view_id="focus",
                selected_visual=prop.selected_visual,
                selection_reason=reason,
            )
        )
    return built


class LlmPresentationPlanner:
    def __init__(self, model: ModelClient):
        self._model = model

    def _build_payload(
        self,
        base_plan: PresentationPlan,
        registry: dict[str, Any],
        findings_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "report_id": base_plan.report_id,
            "subject": base_plan.subject,
            "source_content_revision": base_plan.source_content_revision,
            "sections": [
                {
                    "section_id": section.section_id,
                    "title": section.title,
                    "modules": [
                        {
                            "module_id": module.module_id,
                            "semantic_type": module.semantic_type,
                            "title": module.title,
                            "state": module.state.value,
                            "data_shape": module.data_shape.value,
                            "selected_visual": module.selected_visual.value,
                            "table_columns": list(module.table_columns),
                            "data_profile": _module_data_profile(module),
                            "allowed_visuals": [
                                item.value
                                for item in registry[module.semantic_type].visual_encodings
                            ],
                        }
                        for module in section.modules
                        if module.semantic_type in registry
                    ],
                }
                for section in base_plan.sections
            ],
        }
        if findings_by_id:
            payload["committed_findings"] = [
                {
                    "finding_id": fid,
                    "stakeholder": str(f.get("stakeholder") or ""),
                    "stance": str(f.get("stance") or "unclear"),
                    "response": str(f.get("response") or ""),
                    "text": str(f.get("text") or ""),
                }
                for fid, f in findings_by_id.items()
            ]
        return payload

    def _apply_output(
        self,
        base_plan: PresentationPlan,
        output: VisualPlanOutput,
        registry: dict[str, Any],
        findings_by_id: dict[str, dict[str, Any]] | None = None,
        evidence_by_id: dict[str, dict[str, Any]] | None = None,
        citation_labels: dict[str, str] | None = None,
        citation_refs: dict[str, CitationRef] | None = None,
    ) -> PresentationPlan:
        choices = {choice.module_id: choice for choice in (output.choices or ())}
        dynamic_built = _verify_and_build_dynamic_modules(
            output.dynamic_modules or (),
            findings_by_id or {},
            evidence_by_id or {},
            citation_labels or {},
            citation_refs or {},
            registry,
        )

        sections = []
        for section in base_plan.sections:
            modules = []
            for module in section.modules:
                choice = choices.get(module.module_id)
                if choice is None:
                    modules.append(module)
                    continue
                contract = registry.get(module.semantic_type)
                if contract is None or choice.selected_visual not in contract.visual_encodings:
                    modules.append(module)
                    continue
                if choice.selected_visual is VisualEncoding.DISTRIBUTION_CHART and not module.items:
                    modules.append(module)
                    continue
                updates: dict[str, Any] = {
                    "selected_visual": choice.selected_visual,
                    "selection_reason": choice.reason,
                }
                if choice.title and choice.title.strip():
                    updates["title"] = choice.title.strip()
                if choice.table_columns:
                    updates["table_columns"] = tuple(choice.table_columns)
                modules.append(module.model_copy(update=updates))

            if section.view_id == "focus" and dynamic_built:
                existing_ids = {m.module_id for m in modules}
                for dyn_mod in dynamic_built:
                    if dyn_mod.module_id not in existing_ids:
                        modules.append(dyn_mod)

            sections.append(section.model_copy(update={"modules": tuple(modules)}))
        approved = {
            finding_id for finding_id, finding in (findings_by_id or {}).items()
            if (finding.get("review") or {}).get("verdict") == "supported"
        }
        narrative, dropped = filter_narrative(
            output.narrative, findings_by_id or {}, evidence_by_id or {}, approved
        )
        return base_plan.model_copy(update={
            "sections": tuple(sections),
            "narrative": narrative,
            "profile": {**(base_plan.profile or {}), "narrative_dropped": dropped},
        })

    async def _narrative_retry(self, base_plan, findings_by_id):
        """Ask for the summary on its own when the combined call produced none.

        One call produces choices, dynamic modules and prose together; when that
        payload is truncated the run loses the narrative silently. The retry is a
        much smaller request and only has to return prose.
        """

        from opinion_search.investigation.context import structured_context
        from opinion_search.presentation_skill.llm_planner import NARRATIVE_INSTRUCTIONS

        payload = {
            "focus": base_plan.subject,
            "committed_findings": [
                {"finding_id": fid, "text": (finding.get("text") or "")[:400],
                 "evidence_ids": list(finding.get("evidence_ids") or ())}
                for fid, finding in (findings_by_id or {}).items()
                if (finding.get("review") or {}).get("verdict") == "supported"
            ],
        }
        if not payload["committed_findings"]:
            return None, "no_supported_findings"
        try:
            output = await self._model.decide(
                structured_context(NARRATIVE_INSTRUCTIONS, NarrativeOnlyOutput, payload)
            )
        except Exception as exc:  # noqa: BLE001 - planner failure must not break publishing
            return None, type(exc).__name__
        return output.narrative, None

    async def aplan(
        self,
        base_plan: PresentationPlan,
        *,
        findings_by_id: dict[str, dict[str, Any]] | None = None,
        evidence_by_id: dict[str, dict[str, Any]] | None = None,
        citation_labels: dict[str, str] | None = None,
        citation_refs: dict[str, CitationRef] | None = None,
    ) -> PresentationPlan:
        registry = registry_by_type()
        payload = self._build_payload(base_plan, registry, findings_by_id)
        context = structured_context(PRESENTATION_INSTRUCTIONS, VisualPlanOutput, payload)
        narrative_error = None
        try:
            output = await self._model.decide(context)
        except Exception as exc:  # noqa: BLE001 - publish must not depend on the planner
            output = VisualPlanOutput()
            narrative_error = type(exc).__name__
        if output.narrative is None:
            try:
                narrative, retry_error = await self._narrative_retry(base_plan, findings_by_id or {})
            except Exception as exc:  # noqa: BLE001 - the summary is best effort
                narrative, retry_error = None, type(exc).__name__
            narrative_error = narrative_error or retry_error
            if narrative is not None:
                output = output.model_copy(update={"narrative": narrative})
        planned = self._apply_output(
            base_plan,
            output,
            registry,
            findings_by_id=findings_by_id,
            evidence_by_id=evidence_by_id,
            citation_labels=citation_labels,
            citation_refs=citation_refs,
        )
        if narrative_error:
            planned = planned.model_copy(update={
                "profile": {**(planned.profile or {}), "narrative_error": narrative_error},
            })
        return planned

    def plan(
        self,
        base_plan: PresentationPlan,
        *,
        findings_by_id: dict[str, dict[str, Any]] | None = None,
        evidence_by_id: dict[str, dict[str, Any]] | None = None,
        citation_labels: dict[str, str] | None = None,
        citation_refs: dict[str, CitationRef] | None = None,
    ) -> PresentationPlan:
        return _run_coro_sync(
            self.aplan(
                base_plan,
                findings_by_id=findings_by_id,
                evidence_by_id=evidence_by_id,
                citation_labels=citation_labels,
                citation_refs=citation_refs,
            )
        )
