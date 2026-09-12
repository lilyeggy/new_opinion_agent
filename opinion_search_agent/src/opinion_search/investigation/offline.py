"""Explicitly synthetic fixtures exercising the production investigation machinery."""
import json

from opinion_search.domain.investigation.models import (
    FindingProposal, FinishDecision, IssueAssessment, PlanProposal, QuestionProposal,
    ReadDecision, ReflectDecision, Retirement, ReviewDecision, ReviewItem, ReviewResult,
    SearchDecision, accepted_review,
)
from opinion_search.tools.contracts import ToolAdapterResponse

OFFICIAL = "https://example.org/transport/notice"
REPORT = "https://news.example.org/transport/interview"
PAGES = {
    OFFICIAL: ("夜间公交调整公告（虚构演示）", "演示城市交通部门于2026年1月10日宣布调整夜间公共交通服务，工作日末班时间提前至22时。\n\n官方回应表示将保留周末夜间班次，但没有提供工作日夜班人员替代出行方案。"),
    REPORT: ("夜班人员出行诉求（虚构演示）", "公开采访材料中，两名夜班人员担心公共交通末班提前影响下班出行，希望保留工作日晚班。该材料不代表全体市民意见。\n\n报道指出官方回应仅涉及周末安排，工作日夜班人员的出行问题仍缺少具体解释。"),
}


def offline_plan(request):
    if len(request.question) < 6 and not request.clarification:
        return PlanProposal(subject=request.question, clarification=("请补充事件名称或发生地区，以便确定调查对象。",))
    subject = request.topic or request.question
    # Scripted fixture: facet suggestion mirrors what a real model would
    # propose from the task wording; the program still confirms the names.
    text = f"{request.question} {request.focus or ''}"
    if any(word in text for word in ("水费", "收费", "计费", "票价", "退费", "账单", "补缴")):
        facets, facet_rationale = ("billing_remedy",), "任务文本涉及收费、计费或退费安排。"
    elif any(word in text for word in ("停运", "停用", "恢复", "关闭", "暂停服务")):
        facets, facet_rationale = ("service_change",), "任务文本涉及服务可用性变化。"
    elif any(word in text for word in ("调查", "回应修正", "更正", "处置", "问责")):
        facets, facet_rationale = ("investigation_correction",), "任务文本涉及调查或纠正进展。"
    elif any(word in text for word in ("调整", "新规", "规则", "实施", "提前", "延长", "修改")):
        facets, facet_rationale = ("rule_change",), "任务文本涉及规则内容或适用范围变化。"
    else:
        facets, facet_rationale = (), ""
    return PlanProposal(subject=subject, region=request.region, facets=facets, facet_rationale=facet_rationale,
        questions=tuple(QuestionProposal(question=q) for q in (
            f"{subject}：具体发生了什么调整？", "公开材料中有哪些具体争议和诉求？", "机构回应覆盖哪些问题，哪些仍未回答？")))


class SearchAdapter:
    async def invoke(self, invocation):
        return ToolAdapterResponse(payload={"query": invocation.arguments.query, "items": [{"url": url, "title": data[0], "snippet": data[1][:100]} for url, data in PAGES.items()]})


class ReaderAdapter:
    def __init__(self, update=False):
        self.update = update

    async def invoke(self, invocation):
        url = invocation.arguments.url
        title, content = PAGES[url]
        if self.update and url == OFFICIAL:
            content += "\n\n2026年1月12日补充回应：交通部门宣布在工作日增设23时夜班接驳车，并公布了接驳路线和试运行日期。"
        return ToolAdapterResponse(payload={"url": url, "title": title, "content": content, "published_at": "2026-01-10T09:00:00+08:00"})


class OfflineReviewer:
    def __init__(self, budget):
        self.budget = budget

    async def decide(self, context):
        self.budget.charge("model")
        payload = json.loads(next(s.content for s in context.sections if s.section_id == "input.material"))
        return ReviewResult(items=tuple(ReviewItem(finding_id=f["finding_id"], verdict="supported", reason="演示用预设核查：该主张与固定材料对应；不代表真实模型审查质量。") for f in payload["findings"]))


class OfflineModel:
    def __init__(self, compiler, budget):
        self.compiler, self.budget = compiler, budget

    async def decide(self, context):
        self.budget.charge("model")
        state = self.compiler.state
        if not state.searches:
            return SearchDecision(issue_id=state.issues[0].issue_id, query="演示城市 公共交通 夜间服务 调整 公告", purpose="original")
        unread = next((c for c in state.candidates if c["url"] not in state.read_attempts), None)
        if unread:
            return ReadDecision(issue_id=state.issues[0].issue_id, url=unread["url"], focus="公共交通 调整 工作日 夜班 回应", role="original" if unread["url"] == OFFICIAL else "reporting")
        if any(q.status == "open" for q in state.issues):
            latest = {s.url: s for s in state.sources}
            official = tuple(e for e in state.evidence if e.version_id == latest[OFFICIAL].version_id)
            reporting = tuple(e for e in state.evidence if e.version_id == latest[REPORT].version_id)
            followup = next((e for e in official if "23时" in e.excerpt), None)
            proposals = [
                FindingProposal(issue_id=state.issues[0].issue_id, text="公告称工作日末班时间调整至22时。", kind="attributed", stakeholder="交通部门", evidence_ids=(official[0].evidence_id,), event_time="2026-01-10"),
                FindingProposal(issue_id=state.issues[1].issue_id, text="受访夜班人员希望保留工作日晚班，该采访不能代表全体市民。", kind="request", stakeholder="报道中的受访者", evidence_ids=(reporting[0].evidence_id,), stance="conditional", stance_target="工作日夜间公交安排"),
                FindingProposal(issue_id=state.issues[2].issue_id,
                    text="补充回应公布了工作日23时接驳车安排；实际运行效果仍需观察。" if followup else "原回应涉及周末安排，尚未给出工作日夜班人员替代出行方案。",
                    kind="interpretation", stakeholder="交通部门", response="direct" if followup else "partial",
                    response_target="工作日夜间出行安排",
                    covered=("工作日夜间接驳安排",) if followup else ("周末夜间班次",),
                    uncovered=() if followup else ("工作日夜班人员替代出行",),
                    coverage_reason="补充回应给出了接驳时间与路线。" if followup else "回应只涉及周末安排，未覆盖工作日夜班出行。",
                    evidence_ids=(followup.evidence_id,) if followup else tuple(e.evidence_id for e in official)),
            ]
            for issue in state.issues[3:]:
                if issue.status != "open":
                    continue
                evidence = official or reporting
                proposals.append(FindingProposal(issue_id=issue.issue_id, text=f"依据已读取的公开材料，对“{issue.question}”目前只能作出限定说明。", kind="interpretation", stakeholder="公开材料", response="partial", response_target=issue.question, uncovered=(issue.question,), coverage_reason="公开材料未逐项回应此问题。", evidence_ids=(evidence[0].evidence_id,)))
            assessments = tuple(IssueAssessment(issue_id=p.issue_id, status="answered", reason="按公开材料限定了结论范围。", evidence_ids=p.evidence_ids) for p in proposals)
            retirements = tuple(Retirement(finding_id=f.finding_id, reason="本版材料更新，原判断由重新取证后的判断替代。") for f in state.findings if f.active)
            return ReflectDecision(findings=tuple(proposals), assessments=assessments, retirements=retirements, reason="依据本版材料更新争议及回应分析；历史材料保留。")
        unchecked = [f.finding_id for f in state.findings if f.active and accepted_review(state, f) is None]
        if unchecked:
            return ReviewDecision(finding_ids=tuple(unchecked[:8]))
        return FinishDecision(conclusion_ids=tuple(f.finding_id for f in state.findings if f.active)[:8])
