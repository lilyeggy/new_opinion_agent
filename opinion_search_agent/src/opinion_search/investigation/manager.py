from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import threading
from uuid import uuid4

from opinion_search.app.config import LiveConfig
from opinion_search.domain.investigation.models import InvestigationRequest, Issue, PlanProposal, QuestionProposal, State, uid, utcnow
from opinion_search.domain.investigation.engine import allowed_url
from opinion_search.domain.opinion.framing import build_task_frame
from opinion_search.investigation.context import structured_context
from opinion_search.investigation.export import render_page
from opinion_search.investigation.presentation import confirmed_profile
from opinion_search.investigation.report import build_report, diff_reports, markdown
from opinion_search.investigation.workbench import build_workbench
from opinion_search.investigation.service import PLAN_INSTRUCTIONS, PROFILE, InvestigationRun, build_loop, live_model
from opinion_search.investigation.storage import Budget, CaseBusy, CaseLock, Corpus, atomic_json, atomic_text, read_json, verify_evidence
from opinion_search.runtime.cancellation import EventCancellationSignal
from opinion_search.runtime.checkpoint import JsonCheckpointStore

TERMINAL = {"completed", "partial", "failed", "cancelled"}
ID_RE = re.compile(r"^[a-f0-9]{32}$")
_QUESTION_SPLIT = re.compile(r"[\n\r；;]+|(?<=[。！!？?])")
UPDATE_FIELDS = {"focus", "issue_ids", "finding_ids", "client_request_id"}


def budget_limits() -> dict[str, int]:
    """Read per-run investigation limits, letting slow live models be given more time.

    Defaults keep the original single-machine envelope; a slower provider only needs
    ``OPINION_INVESTIGATION_SECONDS`` raised rather than a code change.
    """
    names = {
        "OPINION_INVESTIGATION_SEARCHES": "search",
        "OPINION_INVESTIGATION_READS": "read",
        "OPINION_INVESTIGATION_MODEL_CALLS": "model",
        "OPINION_INVESTIGATION_SECONDS": "seconds",
        "OPINION_INVESTIGATION_CONSOLIDATE_SECONDS": "consolidate_seconds",
    }
    limits: dict[str, int] = {}
    for variable, key in names.items():
        raw = os.environ.get(variable)
        if raw is None or not raw.strip():
            continue
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{variable} must be a positive integer") from exc
        if value < 1:
            raise ValueError(f"{variable} must be a positive integer")
        limits[key] = value
    return limits


def required_questions(request: InvestigationRequest) -> tuple[str, ...]:
    """Extract the user's explicit questions so they cannot be silently dropped.

    A request only yields required sub-questions when it is written as enumerated
    clauses or question sentences; a plain topic statement keeps an empty set and
    the planner's own questions carry coverage.
    """

    found = []
    for chunk in (request.question, request.focus or ""):
        if not chunk or not ("\n" in chunk or "；" in chunk or ";" in chunk or "?" in chunk or "？" in chunk):
            continue
        for part in _QUESTION_SPLIT.split(chunk):
            part = part.strip(" \t　。；;！!？?")
            if len(part) >= 4:
                found.append(part)
    return tuple(dict.fromkeys(found))


def _cover_required(issues: tuple[Issue, ...], required: tuple[str, ...]) -> tuple[Issue, ...]:
    """Add one grouped issue for any explicit user question the plan left uncovered."""

    covered = {text for issue in issues for text in issue.origin_questions}
    missing = [text for text in required if text not in covered]
    if missing:
        question = "；".join(missing)
        issues = (*issues, Issue(issue_id=uid("issue", question), question=question, required=True, origin_questions=tuple(missing)))
    if len(issues) > 8:
        raise ValueError("the investigation plan exceeds the supported question count")
    return issues


@dataclass
class Worker:
    thread: threading.Thread | None = None
    loop: asyncio.AbstractEventLoop | None = None
    signal: EventCancellationSignal | None = None
    cancelled: bool = False


class Manager:
    """Local event/version orchestration; the AgentLoop owns step transactions."""

    def __init__(self, root: Path, config_loader=None):
        self.root = root
        self.config_loader = config_loader or LiveConfig.from_env
        self.workers: dict[str, Worker] = {}
        self.mutex = threading.RLock()

    def path(self, identifier):
        if not ID_RE.fullmatch(identifier):
            raise ValueError("Invalid investigation identifier.")
        return self.root / "runs" / identifier

    def load(self, identifier):
        data = read_json(self.path(identifier) / "draft.json")
        if data is None:
            raise FileNotFoundError("Investigation not found.")
        return data

    def save(self, data, **changes):
        data = {**data, **changes, "updated_at": utcnow().isoformat()}
        atomic_json(self.path(data["run_id"]) / "draft.json", data)
        return data

    def create(self, payload, parent_id=None):
        payload = dict(payload)
        mode = payload.pop("mode", "live")
        if mode not in {"live", "offline"}:
            raise ValueError("mode must be live or offline")
        parent = self.load(parent_id) if parent_id else None
        followup = {}
        if parent:
            if parent["status"] not in {"completed", "partial"}:
                raise ValueError("Only completed or partial reports can be updated.")
            mode = parent["mode"]
            if set(payload) - UPDATE_FIELDS:
                raise ValueError("An update accepts a supplementary focus and optional targeted references.")
            followup = self._validate_followup(parent, payload)
            replay = self._replay_client_request(parent, payload)
            if replay is not None:
                return replay
            base = dict(parent["request"])
            base["focus"] = payload.get("focus") or base.get("focus")
            payload = base
        request = InvestigationRequest.model_validate(payload)
        if mode == "live":
            self.config_loader()
        identifier = uuid4().hex
        case_id = parent["case_id"] if parent else uuid4().hex
        case_root = self.root / "cases" / case_id
        lock = CaseLock(case_root / "active.lock")
        try:
            for item in self.list_runs():
                if item["case_id"] == case_id and item["status"] not in TERMINAL:
                    raise CaseBusy("This event already has an unfinished investigation.")
            data = {"run_id": identifier, "case_id": case_id, "parent_id": parent_id, "mode": mode,
                    "request": request.model_dump(mode="json"), "status": "planning", "phase": "明确事件与问题",
                    "created_at": utcnow().isoformat(), "clarification_questions": [], "progress": {}, "plan": None,
                    "followup": followup or None}
            self.save(data)
            if followup.get("client_request_id"):
                self._register_client_request(case_root, followup["client_request_id"], followup["request_hash"], identifier)
            self._launch(identifier, lock)
        except BaseException:
            lock.close()
            raise
        return self.snapshot(identifier)

    @staticmethod
    def _followup_digest(payload, parent_id):
        content = {key: value for key, value in payload.items() if key != "client_request_id"}
        content["parent_id"] = parent_id
        return sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _validate_followup(self, parent, payload):
        """Validate targeted references against the parent published version.

        References the frontend sends are promises about parent content; a
        reference outside the parent version must fail here instead of silently
        steering the new run at nothing.
        """

        report = read_json(self.path(parent["run_id"]) / "report.json") or {}
        issues = tuple(payload.get("issue_ids") or ())
        findings = tuple(payload.get("finding_ids") or ())
        known_issues = {x["issue_id"] for x in report.get("issues", [])}
        known_findings = {x["finding_id"] for x in report.get("findings", [])}
        if any(i not in known_issues for i in issues):
            raise ValueError("An update issue reference does not belong to the parent version.")
        if any(i not in known_findings for i in findings):
            raise ValueError("An update finding reference does not belong to the parent version.")
        key = payload.get("client_request_id")
        if key is not None and (not isinstance(key, str) or not key.strip() or len(key) > 200):
            raise ValueError("client_request_id must be a short non-empty string.")
        return {"issue_ids": list(issues), "finding_ids": list(findings),
                "client_request_id": key, "request_hash": self._followup_digest(payload, parent["run_id"])}

    def _replay_client_request(self, parent, payload):
        key = payload.get("client_request_id")
        if not key:
            return None
        registry = read_json(self.root / "cases" / parent["case_id"] / "requests.json") or {}
        entry = registry.get(key)
        if entry is None:
            return None
        if entry.get("payload_hash") != self._followup_digest(payload, parent["run_id"]):
            raise ValueError("client_request_id was reused with different content.")
        return self.snapshot(entry["run_id"])

    def _register_client_request(self, case_root, key, digest, run_id):
        path = case_root / "requests.json"
        registry = read_json(path) or {}
        registry[key] = {"payload_hash": digest, "run_id": run_id}
        atomic_json(path, registry)

    def clarify(self, identifier, payload):
        if set(payload) != {"answer"} or not isinstance(payload["answer"], str) or not payload["answer"].strip():
            raise ValueError("A non-empty clarification answer is required.")
        with self.mutex:
            data = self.load(identifier)
            lock = CaseLock(self.root / "cases" / data["case_id"] / "active.lock")
            try:
                data = self.load(identifier)
                if data["status"] != "needs_clarification":
                    raise ValueError("This investigation is not awaiting clarification.")
                request = dict(data["request"])
                request["clarification"] = (request.get("clarification") or "") + "\n" + payload["answer"].strip()
                time_match = re.search(r"\d{4}-\d{2}-\d{2}\s*(?:至|to|~)\s*\d{4}-\d{2}-\d{2}", payload["answer"])
                if time_match:
                    request["time_range"] = time_match.group()
                elif "不限时间" in payload["answer"]:
                    request["time_range"] = None
                self.save(data, request=request, status="planning", clarification_questions=[])
                self._launch(identifier, lock)
            except BaseException:
                lock.close()
                raise
        return self.snapshot(identifier)

    def resume(self, identifier):
        with self.mutex:
            data = self.load(identifier)
            if data["status"] in TERMINAL or data["status"] == "needs_clarification":
                return self.snapshot(identifier)
            run_path = self.path(identifier) / "run.json"
            if run_path.exists():
                raw = read_json(run_path)
                if not isinstance(raw, dict) or raw.get("execution_profile") != PROFILE:
                    raise ValueError("This investigation was written by an incompatible version and cannot be resumed.")
            lock = CaseLock(self.root / "cases" / data["case_id"] / "active.lock")
            self._launch(identifier, lock)
        return self.snapshot(identifier)

    def cancel(self, identifier):
        with self.mutex:
            data = self.load(identifier)
            worker = self.workers.get(identifier)
            if worker and worker.thread and worker.thread.is_alive():
                worker.cancelled = True
                if worker.loop and worker.signal:
                    worker.loop.call_soon_threadsafe(worker.signal.cancel)
            elif data["status"] not in TERMINAL:
                lock = CaseLock(self.root / "cases" / data["case_id"] / "active.lock")
                try:
                    self._cancel_publish(identifier, data)
                finally:
                    lock.close()
        return self.snapshot(identifier)

    def list_runs(self):
        paths = list((self.root / "runs").glob("*/draft.json"))
        values = [read_json(path) for path in paths]
        return sorted(values, key=lambda d: d["created_at"], reverse=True)

    def _domain_state(self, identifier):
        raw = read_json(self.path(identifier) / "run.json")
        if raw is None or "state" not in raw:
            raise FileNotFoundError("This investigation has no committed state yet.")
        try:
            return InvestigationRun.model_validate(raw["state"]).domain_state
        except ValueError as exc:
            raise ValueError("This investigation was written by an incompatible version.") from exc

    def _write_provisional_workbench(self, identifier, data, state):
        """In-run stage projection using the same contract as published views.

        Everything a running page shows from here stays provisional: findings
        that have not passed review can never enter the published core.
        """

        try:
            report = build_report(state, "running", "调查进行中的阶段投影，内容待审查。",
                case_id=data["case_id"], run_id=identifier, mode=data["mode"])
            atomic_json(self.path(identifier) / "workbench-provisional.json", build_workbench(report))
        except ValueError:
            # A state that predates the workbench contract keeps progress-only output.
            return

    def workbench(self, identifier, snapshot_id=None):
        """A consistent workbench projection bound to the published version.

        A caller that pins ``snapshot_id`` always gets that exact view or a
        conflict: silently switching to the newest snapshot would mix content
        from different versions in one page.
        """

        report = read_json(self.path(identifier) / "report.json")
        if report is None:
            provisional = read_json(self.path(identifier) / "workbench-provisional.json")
            if provisional is None:
                raise FileNotFoundError("The workbench is available once material has been committed.")
            projection = provisional
        else:
            projection = build_workbench(report)
        if snapshot_id and snapshot_id != projection["snapshot_id"]:
            raise ValueError("The requested workbench snapshot does not match this version; reload the current one.")
        return projection

    def markdown(self, identifier):
        path = self.path(identifier) / "report.md"
        if not path.is_file():
            raise FileNotFoundError("The report is written when the investigation reaches a terminal state.")
        return path.read_text(encoding="utf-8")

    def report(self, identifier):
        report = read_json(self.path(identifier) / "report.json")
        if report is None:
            raise FileNotFoundError("The report is written when the investigation reaches a terminal state.")
        return report

    def evidence(self, identifier, evidence_id):
        """Locate one reviewed excerpt inside its immutable source version."""

        import asyncio

        data = self.load(identifier)
        state = self._domain_state(identifier)
        item = next((e for e in state.evidence if e.evidence_id == evidence_id), None)
        if item is None:
            raise KeyError("unknown evidence")
        source = next((s for s in state.sources if s.version_id == item.version_id), None)
        if source is None:
            raise ValueError("evidence references an unknown source version")
        relations = [{"finding_id": f.finding_id, "issue_id": f.issue_id,
                      "relation": "contradict" if item.evidence_id in f.contradicting_ids else "support"}
                     for f in state.findings
                     if item.evidence_id in f.evidence_ids or item.evidence_id in f.contradicting_ids]
        if data.get("status") in TERMINAL:
            content = asyncio.run(Corpus(self.root / "cases" / data["case_id"]).artifacts.get_text(source.artifact_ref))
            verify_evidence(item, content)
            before = content[max(0, item.start - 240):item.start]
            after = content[item.end:item.end + 240]
        else:
            before = after = ""
        return {
            "evidence_id": item.evidence_id, "excerpt": item.excerpt, "start": item.start, "end": item.end,
            "locator": item.locator, "before": before, "after": after, "relations": relations,
            "source": {"version_id": source.version_id, "title": source.title, "url": source.url,
                       "final_url": source.final_url, "fetched_at": source.fetched_at.isoformat(),
                       "published_at": source.published_at.isoformat() if source.published_at else None,
                       "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                       "content_hash": source.content_hash, "role": source.role},
        }

    def versions(self, identifier):
        data = self.load(identifier)
        runs = [d for d in self.list_runs() if d["case_id"] == data["case_id"]]
        return [{"run_id": d["run_id"], "parent_id": d["parent_id"], "status": d["status"],
                 "created_at": d["created_at"], "phase": d.get("phase", ""), "is_current": d["run_id"] == identifier}
                for d in sorted(runs, key=lambda x: x["created_at"])]

    def page(self, identifier, snapshot_id=None):
        """Render one committed snapshot as a self-contained HTML document.

        The export consumes the same projection as the interactive page, so the
        downloaded file can never disagree with the online version it came from.
        """

        projection = self.workbench(identifier, snapshot_id)
        report = read_json(self.path(identifier) / "report.json")
        return render_page(projection, report=report, evidence_context=self._evidence_context(identifier))

    def _evidence_context(self, identifier):
        """Bounded before/after context for each saved excerpt, read once."""

        try:
            state = self._domain_state(identifier)
            data = self.load(identifier)
        except (FileNotFoundError, ValueError):
            return {}
        if data.get("status") not in TERMINAL:
            return {}
        corpus = Corpus(self.root / "cases" / data["case_id"])
        contents = {}
        for source in state.sources:
            try:
                contents[source.version_id] = asyncio.run(corpus.artifacts.get_text(source.artifact_ref))
            except (OSError, ValueError):
                continue
        contexts = {}
        for item in state.evidence:
            content = contents.get(item.version_id)
            if content is None:
                continue
            try:
                verify_evidence(item, content)
            except ValueError:
                # Unverifiable excerpts are never faked into the export.
                continue
            contexts[item.evidence_id] = {"before": content[max(0, item.start - 240):item.start],
                                          "after": content[item.end:item.end + 240]}
        return contexts

    def materials(self, identifier, issue_id=None, snapshot_id=None, offset=0, limit=50):
        """Filter materials inside one snapshot; totals share the same membership."""

        report = self.report(identifier)
        projection = build_workbench(report)
        if snapshot_id and snapshot_id != projection["snapshot_id"]:
            raise ValueError("The requested workbench snapshot does not match this version; reload the current one.")
        sources = report.get("sources", [])
        if issue_id is not None:
            if issue_id not in {x["issue_id"] for x in report.get("issues", [])}:
                raise ValueError("The requested issue does not belong to this version.")
            linked = {eid for f in report.get("findings", []) if f["issue_id"] == issue_id
                      for eid in list(f.get("evidence_ids", [])) + list(f.get("contradicting_ids", []))}
            version_ids = {e["version_id"] for e in report.get("evidence", []) if e["evidence_id"] in linked}
            sources = [s for s in sources if s["version_id"] in version_ids]
        total = len(sources)
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 100))
        return {"snapshot_id": projection["snapshot_id"], "issue_id": issue_id, "total": total,
                "offset": offset, "limit": limit, "materials": sources[offset:offset + limit]}

    def diff(self, identifier, base_id):
        current = self.report(identifier)
        base_id = base_id or self.load(identifier).get("parent_id")
        if not base_id:
            raise ValueError("This version has no parent version to compare with.")
        base = self.report(base_id)
        if current["case_id"] != base["case_id"]:
            raise ValueError("Only versions of the same event can be compared.")
        return {"run_id": identifier, "base": base_id, "changes": diff_reports(current, base),
                "comparability": {"same_case": True, "current_cutoff": current["cutoff"],
                                  "base_cutoff": base["cutoff"],
                                  "current_status": current["status"], "base_status": base["status"],
                                  "note": "两版为同一事件的版本化结果；若后续改变采集、分类或去重口径，将在此标注不可直接比较。"}}

    def snapshot(self, identifier):
        data = self.load(identifier)
        output = dict(data)
        worker = self.workers.get(identifier)
        output["resumable"] = False
        if data["status"] not in TERMINAL | {"needs_clarification"} and not (worker and worker.thread and worker.thread.is_alive()):
            try:
                lock = CaseLock(self.root / "cases" / data["case_id"] / "active.lock")
            except CaseBusy:
                pass
            else:
                output["resumable"] = True
                lock.close()
        report = read_json(self.path(identifier) / "report.json")
        if report and data["status"] in TERMINAL:
            output["report"] = report
            output["workbench_revision"] = build_workbench(report)["snapshot_id"]
        output["report_pending"] = data["status"] == "finalizing"
        latest_completed = read_json(self.root / "cases" / data["case_id"] / "latest_completed.json")
        if latest_completed and latest_completed.get("run_id") != identifier:
            output["latest_completed_run_id"] = latest_completed["run_id"]
        output["versions"] = [{"run_id": d["run_id"], "parent_id": d["parent_id"], "status": d["status"], "created_at": d["created_at"]} for d in self.list_runs() if d["case_id"] == data["case_id"]]
        return output

    def _launch(self, identifier, lock):
        worker = Worker()
        self.workers[identifier] = worker
        worker.thread = threading.Thread(target=self._worker, args=(identifier, lock, worker), daemon=True, name="investigation-" + identifier)
        worker.thread.start()

    def _worker(self, identifier, lock, worker):
        try:
            asyncio.run(self._investigate(identifier, worker))
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Investigation %s failed", identifier)
            data = self.load(identifier)
            self._publish_failure(identifier, data)
        finally:
            worker.loop = None
            worker.signal = None
            lock.close()

    def _publish_failure(self, identifier, data):
        """Expose the material already committed to the checkpoint for a failed run."""

        run_root = self.path(identifier)
        report = None
        try:
            raw = read_json(run_root / "run.json")
            if raw and "state" in raw:
                run_state = InvestigationRun.model_validate(raw["state"])
                parent_id = data.get("parent_id")
                parent = read_json(self.path(parent_id) / "report.json") if parent_id else None
                budget = read_json(run_root / "budget.json")
                report = build_report(run_state.domain_state, "failed", "调查中断，已保存的材料与判断仍然保留，报告不完整。",
                    case_id=data["case_id"], run_id=identifier, parent_id=parent_id, parent=parent, mode=data["mode"], budget=budget)
                atomic_json(run_root / "report.json", report)
                atomic_text(run_root / "report.md", markdown(report))
        except (OSError, ValueError):
            report = None
        message = "调查未能完成，已保存的材料仍然保留。请检查服务配置或开发者日志。"
        self.save(self.load(identifier), status="failed", phase="调查失败", error=message, published=report is not None)

    def _cancel_publish(self, identifier, data):
        """Publish a cancelled report so a cancelled run is never terminal without one."""

        run_root = self.path(identifier)
        parent_id = data.get("parent_id")
        parent = read_json(self.path(parent_id) / "report.json") if parent_id else None
        budget = read_json(run_root / "budget.json")
        note = "调查在产生可核查材料前已被取消，未完成问题不视为已解决或已撤回。"
        raw = read_json(run_root / "run.json")
        if raw and "state" in raw:
            state = InvestigationRun.model_validate(raw["state"]).domain_state
            report = build_report(state, "cancelled", note, case_id=data["case_id"], run_id=identifier,
                                  parent_id=parent_id, parent=parent, mode=data["mode"], budget=budget)
        else:
            plan = data.get("plan") or {}
            report = {
                "schema_version": 2, "case_id": data["case_id"], "run_id": identifier, "parent_id": parent_id,
                "mode": data["mode"], "subject": plan.get("subject") or data["request"]["question"],
                "question": data["request"]["question"], "status": "cancelled", "stop_reason": note,
                "cutoff": utcnow().isoformat(), "required_questions": [], "issues": [], "findings": [],
                "retired": [], "conclusions": [], "sources": [], "evidence": [], "searches": [], "read_errors": [],
                "changes": [], "no_material_change": False, "budget": budget,
                "scope_limitation": "调查已取消，没有可展示的材料或结论。",
            }
        atomic_json(run_root / "report.json", report)
        atomic_text(run_root / "report.md", markdown(report))
        self.save(self.load(identifier), status="cancelled", phase="已取消", published=True)

    async def _investigate(self, identifier, worker):
        from opinion_search.investigation.offline import offline_plan
        data = self.load(identifier)
        run_root = self.path(identifier)
        case_root = self.root / "cases" / data["case_id"]
        budget = Budget(run_root / "budget.json", budget_limits())
        config = self.config_loader() if data["mode"] == "live" else None
        worker.loop = asyncio.get_running_loop()
        worker.signal = EventCancellationSignal()
        if worker.cancelled:
            worker.signal.cancel()
        request = InvestigationRequest.model_validate(data["request"])
        checkpoint = JsonCheckpointStore(run_root / "run.json", InvestigationRun, execution_profile=PROFILE)
        parent = read_json(self.path(data["parent_id"]) / "report.json") if data["parent_id"] else None
        if not (run_root / "run.json").exists():
            budget.start()
            frame = build_task_frame(request, anchor_date=date.today())
            if request.time_range and not frame.temporal_scope.is_bounded:
                budget.pause()
                self.save(data, status="needs_clarification", phase="需要补充时间范围", clarification_questions=["请提供 YYYY-MM-DD 至 YYYY-MM-DD，或回答“不限时间”。"])
                return
            required = required_questions(request)
            if data.get("plan"):
                plan = PlanProposal.model_validate(data["plan"])
            elif parent:
                plan = PlanProposal(subject=parent["subject"], questions=tuple(QuestionProposal(question=q["question"], required=q["required"]) for q in parent["issues"][:6]))
            elif config:
                payload = {**request.model_dump(mode="json"), "required_questions": list(required)}
                plan = await live_model(config, budget, PlanProposal).decide(structured_context(PLAN_INSTRUCTIONS, PlanProposal, payload))
            else:
                budget.charge("model")
                plan = offline_plan(request)
            if worker.cancelled:
                self._cancel_publish(identifier, data)
                return
            if plan.clarification:
                budget.pause()
                self.save(data, status="needs_clarification", phase="需要明确调查对象", clarification_questions=list(plan.clarification))
                return
            required_set = set(required)
            issues = _cover_required(tuple(
                Issue(issue_id=uid("issue", q.question), question=q.question, required=q.required,
                      origin_questions=tuple(text for text in q.covers if text in required_set))
                for q in plan.questions), required)
            old_state = None
            if parent:
                old_checkpoint = JsonCheckpointStore(self.path(data["parent_id"]) / "run.json", InvestigationRun, execution_profile=PROFILE)
                old_state = (await old_checkpoint.load()).domain_state
                reopened = tuple(q.model_copy(update={"status": "open", "note": "", "evidence_ids": ()}) for q in old_state.issues)
                issues = _cover_required(reopened, required)
            state = State(request=request, subject=plan.subject, aliases=plan.aliases, cutoff=utcnow(), required_questions=required, issues=issues,
                sources=old_state.sources if old_state else (), evidence=old_state.evidence if old_state else (),
                findings=tuple(f.model_copy(update={"active": False}) for f in old_state.findings) if old_state else (),
                # An on-demand update keeps the event's confirmed emphasis: the
                # event type does not change just because we re-investigate it.
                profile=old_state.profile if old_state else confirmed_profile(plan, issues),
                history=("用户请求按需更新，旧判断待重新取证和审查。",) if parent else ())
            references = []
            for url in request.reference_urls:
                if not allowed_url(url, state):
                    raise ValueError("Reference URL is outside the allowed public document scope")
                from opinion_search.tools.url import normalize_public_url
                references.append({"url": normalize_public_url(url), "title": "用户提供的参考链接", "snippet": "尚未读取", "issue_id": issues[0].issue_id})
            if old_state:
                references.extend({"url": s.url, "title": s.title, "snippet": "历史来源，需检查更新", "issue_id": issues[0].issue_id} for s in old_state.sources if allowed_url(s.url, state))
            state = state.model_copy(update={"candidates": tuple({x["url"]: x for x in references}.values())})
            data = self.save(data, plan=plan.model_dump(mode="json"), subject=plan.subject, status="running")
            budget.start()
            await checkpoint.save(InvestigationRun(run_id=identifier, domain_state=state))
        else:
            data = self.save(data, status="running")
        manager = self

        class Hook:
            async def after_checkpoint(self, boundary, run):
                state = run.domain_state
                active = run.active_step
                action = active.decision.decision.action if active and active.decision else "search"
                phase = {"search": "查找原始材料与不同观点", "read": "阅读公开材料", "retrieve": "重新查阅已保存正文", "reflect": "梳理争议与回应", "review": "核查关键结论", "finish": "生成报告"}[action]
                if worker.cancelled:
                    worker.signal.cancel()
                # A terminal runtime status is not yet user-visible: the report must
                # be fully written first, so expose an intermediate publishing state.
                status = "finalizing" if run.status.value in TERMINAL else "running"
                if status == "finalizing":
                    phase = "正在写入报告与版本"
                manager.save(manager.load(identifier), status=status, phase=phase,
                    progress={"questions": [q.model_dump(mode="json") for q in state.issues], "source_count": len(state.sources), "finding_count": sum(f.active for f in state.findings), "read_errors": len(state.read_errors), "search_errors": sum(s.outcome == "error" for s in state.searches)})
                manager._write_provisional_workbench(identifier, data, state)

        loop = build_loop(run_root, case_root, data["mode"], budget, Hook(), worker.signal, config, bool(parent))
        result = await loop.resume()
        await self._publish(identifier, data, result, parent, run_root, case_root, budget)

    async def _publish(self, identifier, data, result, parent, run_root, case_root, budget):
        """Write the immutable report artifacts, then atomically expose the version."""

        status = result.status.value
        report = build_report(result.domain_state, status, result.stop_reason, case_id=data["case_id"], run_id=identifier, parent_id=data["parent_id"], parent=parent, mode=data["mode"], budget=budget.snapshot())
        atomic_json(run_root / "report.json", report)
        atomic_text(run_root / "report.md", markdown(report))
        (run_root / "workbench-provisional.json").unlink(missing_ok=True)
        if status in {"completed", "partial"}:
            atomic_json(case_root / "latest.json", {"run_id": identifier})
        # A complete result keeps its own pointer so a later partial update can
        # never hide the last full judgement of this event.
        if status == "completed":
            atomic_json(case_root / "latest_completed.json", {"run_id": identifier})
        phase = {"completed": "调查完成", "partial": "部分完成", "cancelled": "已取消", "failed": "调查失败"}[status]
        self.save(self.load(identifier), status=status, phase=phase, published=True)
