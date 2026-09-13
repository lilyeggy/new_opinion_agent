"""Explicitly synthetic fixtures exercising the production investigation machinery.

Two complete, non-mixing demo kits are kept separate: a night-bus rule change
and a residential water-billing dispute. The task text selects one kit before
planning, and the same kit drives search, reading and the scripted decisions so
the offline page cannot show one event's conclusion under another event's
materials.
"""
import json

from opinion_search.domain.investigation.models import (
    FACET_MODULE_TYPES, ComponentAssessment, FindingProposal, FinishDecision, IssueAssessment,
    ModuleField, PlanProposal, QuestionProposal, ReadDecision, ReflectDecision, Retirement,
    ReviewDecision, ReviewItem, ReviewResult, SearchDecision, accepted_review,
)
from opinion_search.tools.contracts import ToolAdapterResponse

BUS_OFFICIAL = "https://example.org/transport/notice"
BUS_REPORT = "https://news.example.org/transport/interview"
WATER_OFFICIAL = "https://example.org/water/billing-notice"
WATER_REPORT = "https://news.example.org/water/interview"

_WATER_WORDS = ("水费", "水价", "退费", "账单", "补缴", "阶梯水价")
_BUS_WORDS = ("公交", "地铁", "夜班", "夜间", "末班", "接驳")
_PRICE_WORDS = ("收费", "计费", "票价")

FIXTURES = {
    "bus": {
        "label": "夜间公交调整",
        "pages": {
            BUS_OFFICIAL: (
                "夜间公交调整公告（虚构演示）",
                "演示城市交通部门于2026年1月10日宣布调整夜间公共交通服务，工作日末班时间提前至22时。\n\n"
                "官方回应表示将保留周末夜间班次，但没有提供工作日夜班人员替代出行方案。",
            ),
            BUS_REPORT: (
                "夜班人员出行诉求（虚构演示）",
                "公开采访材料中，两名夜班人员担心公共交通末班提前影响下班出行，希望保留工作日晚班。"
                "该材料不代表全体市民意见。\n\n报道指出官方回应仅涉及周末安排，工作日夜班人员的出行问题仍缺少具体解释。",
            ),
        },
        "official_url": BUS_OFFICIAL,
        "report_url": BUS_REPORT,
        "search_query": "演示城市 公共交通 夜间服务 调整 公告",
        "published_at": "2026-01-10T09:00:00+08:00",
        "read_focus": "公共交通 调整 工作日 夜班 回应",
        "update_marker": "2026年1月12日补充回应",
        "update_text": "\n\n2026年1月12日补充回应：交通部门宣布在工作日增设23时夜班接驳车，并公布了接驳路线和试运行日期。",
        "original_finding": {
            "text": "公告称工作日末班时间调整至22时。",
            "stakeholder": "交通部门",
            "event_time": "2026-01-10",
            "module_fields": (
                ("rule-comparison", "new_value", "工作日末班时间提前至22时"),
                ("rule-comparison", "applies_to", "工作日夜间公交"),
                ("rule-comparison", "effective_time", "2026-01-10"),
            ),
        },
        "public_finding": {
            "text": "受访夜班人员希望保留工作日晚班，该采访不能代表全体市民。",
            "stakeholder": "报道中的受访者",
            "stance_target": "工作日夜间公交安排",
        },
        "response_base": {
            "text": "原回应涉及周末安排，尚未给出工作日夜班人员替代出行方案。",
            "response_target": "工作日夜间出行安排",
            "covered": ("周末夜间班次",),
            "uncovered": ("工作日夜班人员替代出行",),
            "coverage_reason": "回应只涉及周末安排，未覆盖工作日夜班出行。",
        },
        "response_update": {
            "text": "补充回应公布了工作日23时接驳车安排；实际运行效果仍需观察。",
            "response_target": "工作日夜间出行安排",
            "covered": ("工作日夜间接驳安排",),
            "uncovered": (),
            "coverage_reason": "补充回应给出了接驳时间与路线。",
            "module_fields": (
                ("rule-comparison", "transition", "工作日增设23时夜班接驳车，并公布接驳路线和试运行日期"),
            ),
        },
        "response_target": "工作日夜间出行安排",
    },
    "water": {
        "label": "阶梯水价计费争议",
        "pages": {
            WATER_OFFICIAL: (
                "居民阶梯水价计费说明（虚构演示）",
                "某市自来水公司于2026年3月2日发布说明称，居民阶梯水价自2026年2月抄见水量起调整，"
                "第一阶梯用水量上限由15吨调整为12吨。用户可通过营业厅或线上渠道申请账单复核，"
                "公司将在5个工作日内答复。\n\n说明没有给出多收费用如何处理的具体口径。",
            ),
            WATER_REPORT: (
                "居民反映水费上涨与退费诉求（虚构演示）",
                "公开采访材料中，多位居民表示未提前收到调价通知，希望公开计费明细并复核多收费用。"
                "该采访不能代表全体用户意见。\n\n报道指出公司仅说明可以申请复核，但没有公布退费标准与期限。",
            ),
        },
        "official_url": WATER_OFFICIAL,
        "report_url": WATER_REPORT,
        "search_query": "某市 自来水 阶梯水价 调整 计费 复核",
        "published_at": "2026-03-02T09:00:00+08:00",
        "read_focus": "水价 调整 计费 复核 退费 回应",
        "update_marker": "2026年3月12日补充说明",
        "update_text": "\n\n2026年3月12日补充说明：对3月账单有异议的用户可在30日内申请复核，经核实多收部分将按原渠道退回，无需额外申请。",
        "original_finding": {
            "text": "说明称居民阶梯水价自2026年2月抄见水量起调整，第一阶梯上限由15吨调整为12吨。",
            "stakeholder": "自来水公司",
            "event_time": "2026-03-02",
            "module_fields": (
                ("billing-remedy", "billing_basis", "居民阶梯水价自2026年2月抄见水量起调整，第一阶梯上限由15吨调整为12吨"),
                ("billing-remedy", "scope", "居民用户"),
                ("billing-remedy", "handling_path", "可通过营业厅或线上渠道申请账单复核"),
                ("billing-remedy", "deadline", "公司将在5个工作日内答复"),
            ),
        },
        "public_finding": {
            "text": "受访居民希望公开计费明细并复核多收费用；该采访不能代表全体用户。",
            "stakeholder": "报道中的受访居民",
            "stance_target": "居民阶梯水价计费与退费安排",
        },
        "response_base": {
            "text": "说明给出了阶梯水价执行时间与复核渠道，但没有说明多收费用的退费标准与期限。",
            "response_target": "多收费用的复核与退还安排",
            "covered": ("调整生效时间", "第一阶梯水量上限", "账单复核渠道"),
            "uncovered": ("多收费用退费标准", "退费办理时限"),
            "coverage_reason": "说明仅给出计费规则与复核渠道，未说明退费标准。",
        },
        "response_update": {
            "text": "补充说明明确复核后多收部分按原渠道退回，并给出30日申请期限；实际到账情况仍需观察。",
            "response_target": "多收费用的复核与退还安排",
            "covered": ("复核申请期限", "多收部分退还方式"),
            "uncovered": (),
            "coverage_reason": "补充说明给出了复核期限与多收费用退还方式。",
            "module_fields": (
                ("billing-remedy", "remedy_commitment", "经核实多收部分按原渠道退回，30日内可申请复核"),
            ),
        },
        "response_target": "多收费用的复核与退还安排",
    },
}

# Compatibility for the first fixture; callers should select a fixture explicitly.
PAGES = FIXTURES["bus"]["pages"]


def fixture_for_request(request) -> str:
    """Pick one complete demo kit from the task text before planning starts."""

    text = f"{request.question} {request.focus or ''}"
    if any(word in text for word in _WATER_WORDS):
        return "water"
    if any(word in text for word in _BUS_WORDS):
        return "bus"
    return "water" if any(word in text for word in _PRICE_WORDS) else "bus"


def fixture_data(name: str) -> dict:
    return FIXTURES.get(name) or FIXTURES["bus"]


def _module_fields(item: dict, state) -> tuple[ModuleField, ...]:
    if state.profile is None:
        return ()
    allowed = {FACET_MODULE_TYPES[facet] for facet in state.profile.facets if facet in FACET_MODULE_TYPES}
    return tuple(ModuleField(module=module, field=key, value=value)
                 for module, key, value in item.get("module_fields", ()) if module in allowed)


def offline_plan(request):
    if len(request.question) < 6 and not request.clarification:
        return PlanProposal(subject=request.question, clarification=("请补充事件名称或发生地区，以便确定调查对象。",))
    subject = request.topic or request.question
    # Scripted fixture: the model-side facet suggestion mirrors the selected
    # kit; the program still confirms the names before any module is shown.
    if fixture_for_request(request) == "water":
        facets, facet_rationale = ("billing_remedy",), "任务文本涉及收费、计费或退费安排。"
    else:
        text = f"{request.question} {request.focus or ''}"
        if any(word in text for word in ("停运", "停用", "恢复", "关闭", "暂停服务")):
            facets, facet_rationale = ("service_change",), "任务文本涉及服务可用性变化。"
        elif any(word in text for word in ("调查", "回应修正", "更正", "处置", "问责")):
            facets, facet_rationale = ("investigation_correction",), "任务文本涉及调查或纠正进展。"
        elif any(word in text for word in ("调整", "新规", "规则", "实施", "提前", "延长", "修改")):
            facets, facet_rationale = ("rule_change",), "任务文本涉及规则内容或适用范围变化。"
        else:
            facets, facet_rationale = (), ""
    return PlanProposal(subject=subject, region=request.region, facets=facets, facet_rationale=facet_rationale,
        questions=(
            QuestionProposal(question=f"{subject}：具体发生了什么调整？",
                             components=("核心事实与变化", "适用范围或对象", "执行或生效安排")),
            QuestionProposal(question="公开材料中有哪些具体争议和诉求？",
                             components=("受影响主体", "具体诉求与争议")),
            QuestionProposal(question="机构回应覆盖哪些问题，哪些仍未回答？",
                             components=("机构已回应内容", "仍未回答事项")),
        ))


class SearchAdapter:
    def __init__(self, fixture: str = "bus"):
        self.fixture = fixture_data(fixture)

    async def invoke(self, invocation):
        return ToolAdapterResponse(payload={"query": invocation.arguments.query,
            "items": [{"url": url, "title": data[0], "snippet": data[1][:100]}
                      for url, data in self.fixture["pages"].items()]})


class ReaderAdapter:
    def __init__(self, update=False, fixture: str = "bus"):
        self.update = update
        self.fixture = fixture_data(fixture)

    async def invoke(self, invocation):
        url = invocation.arguments.url
        title, content = self.fixture["pages"][url]
        if self.update and url == self.fixture["official_url"]:
            content += self.fixture["update_text"]
        return ToolAdapterResponse(payload={"url": url, "title": title, "content": content,
            "published_at": self.fixture["published_at"]})


class OfflineReviewer:
    def __init__(self, budget):
        self.budget = budget

    async def decide(self, context):
        self.budget.charge("model")
        payload = json.loads(next(s.content for s in context.sections if s.section_id == "input.material"))
        return ReviewResult(items=tuple(ReviewItem(finding_id=f["finding_id"], verdict="supported",
            reason="演示用预设核查：该主张与固定材料对应；不代表真实模型审查质量。") for f in payload["findings"]))


class OfflineModel:
    def __init__(self, compiler, budget, fixture: str = "bus"):
        self.compiler, self.budget = compiler, budget
        self.fixture = fixture_data(fixture)

    async def decide(self, context):
        self.budget.charge("model")
        state = self.compiler.state
        if not state.searches:
            return SearchDecision(issue_id=state.issues[0].issue_id, query=self.fixture["search_query"], purpose="original")
        unread = next((c for c in state.candidates if c["url"] not in state.read_attempts), None)
        if unread:
            return ReadDecision(issue_id=state.issues[0].issue_id, url=unread["url"], focus=self.fixture["read_focus"],
                                role="original" if unread["url"] == self.fixture["official_url"] else "reporting")
        if any(q.status == "open" for q in state.issues):
            official = self._evidence_for_url(state, self.fixture["official_url"])
            reporting = self._evidence_for_url(state, self.fixture["report_url"])
            fallback = tuple(state.evidence)
            followup = next((e for e in official if self.fixture["update_marker"] in e.excerpt), None)
            proposals = []
            for issue in state.issues:
                if issue.status != "open":
                    continue
                kind = self._issue_kind(issue.question)
                if kind == "public" and reporting:
                    item = self.fixture["public_finding"]
                    proposals.append(FindingProposal(issue_id=issue.issue_id, text=item["text"], kind="request",
                        stakeholder=item["stakeholder"], evidence_ids=(reporting[0].evidence_id,),
                        stance="conditional", stance_target=item["stance_target"],
                        module_fields=_module_fields(item, state)))
                elif kind == "response" and (followup or official):
                    body = self.fixture["response_update"] if followup else self.fixture["response_base"]
                    evidence_ids = (followup.evidence_id,) if followup else tuple(e.evidence_id for e in official)
                    proposals.append(FindingProposal(issue_id=issue.issue_id, text=body["text"], kind="interpretation",
                        stakeholder="机构回应", response="direct" if followup else "partial",
                        response_target=body["response_target"], covered=body["covered"], uncovered=body["uncovered"],
                        coverage_reason=body["coverage_reason"], evidence_ids=evidence_ids,
                        module_fields=_module_fields(body, state)))
                elif official:
                    item = self.fixture["original_finding"]
                    proposals.append(FindingProposal(issue_id=issue.issue_id, text=item["text"], kind="attributed",
                        stakeholder=item["stakeholder"], evidence_ids=(official[0].evidence_id,),
                        event_time=item["event_time"], module_fields=_module_fields(item, state)))
                else:
                    pool = reporting or fallback
                    if not pool:
                        continue
                    proposals.append(FindingProposal(issue_id=issue.issue_id,
                        text=f"依据已读取的公开材料，对“{issue.question}”目前只能作出限定说明。",
                        kind="interpretation", stakeholder="公开材料", response="partial",
                        response_target=issue.question, uncovered=(issue.question,),
                        coverage_reason="公开材料未逐项回应此问题。", evidence_ids=(pool[0].evidence_id,)))
            issue_by_id = {issue.issue_id: issue for issue in state.issues}
            assessments = tuple(IssueAssessment(
                issue_id=p.issue_id, status="answered", reason="按公开材料限定了结论范围。",
                evidence_ids=p.evidence_ids,
                components=tuple(ComponentAssessment(text=component.text, status="answered",
                                                     evidence_ids=p.evidence_ids,
                                                     note="按公开材料限定了该子项。")
                                 for component in issue_by_id[p.issue_id].components))
                for p in proposals)
            open_ids = {q.issue_id for q in state.issues if q.status == "open"}
            retirements = tuple(Retirement(finding_id=f.finding_id,
                reason="本版材料更新，原判断由重新取证后的判断替代。")
                for f in state.findings if f.active and f.issue_id in open_ids)
            return ReflectDecision(findings=tuple(proposals), assessments=assessments,
                retirements=retirements, reason="依据本版材料更新争议及回应分析；历史材料保留。")
        unchecked = [f.finding_id for f in state.findings if f.active and accepted_review(state, f) is None]
        if unchecked:
            return ReviewDecision(finding_ids=tuple(unchecked[:8]))
        return FinishDecision(conclusion_ids=tuple(f.finding_id for f in state.findings if f.active)[:8])

    def _evidence_for_url(self, state, url):
        versions = [s.version_id for s in state.sources if s.url == url]
        if not versions:
            return ()
        latest = versions[-1]
        return tuple(e for e in state.evidence if e.version_id == latest)

    @staticmethod
    def _issue_kind(question: str) -> str:
        if any(word in question for word in ("具体发生了什么", "发生了什么", "具体是什么调整")):
            return "original"
        if any(word in question for word in ("回应", "回答", "覆盖", "未回答")):
            return "response"
        if any(word in question for word in ("争议", "诉求", "不同", "分歧")):
            return "public"
        return "original"
