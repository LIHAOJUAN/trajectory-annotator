#!/usr/bin/env python3
"""Local web UI for SWE-bench trajectory review and manual annotation."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import fcntl
from datetime import datetime, timezone
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ANNOTATOR_DATA_DIR", ROOT / "data")).resolve()
OUTPUTS_DIR = DATA_DIR / "outputs"
REPLAY_DIR = OUTPUTS_DIR / "checkpoint_replay"
SAMPLE_FILE = os.environ.get("ANNOTATOR_SAMPLE_FILE", "annotation_sample_100.jsonl")
SAMPLE_PATH = Path(SAMPLE_FILE)
if not SAMPLE_PATH.is_absolute():
    SAMPLE_PATH = DATA_DIR / SAMPLE_PATH
SCHEMA_PATH = DATA_DIR / "trajectory_review.schema.json"
TRAJECTORY_ROOT_VALUE = os.environ.get("SWE_TRAJECTORY_ROOT", "").strip()
TRAJECTORY_ROOT = Path(TRAJECTORY_ROOT_VALUE).resolve() if TRAJECTORY_ROOT_VALUE else None
REVIEW_STORE_PATH = Path(os.environ.get(
    "ANNOTATOR_REVIEW_STORE_PATH", ROOT / "workspace" / "trajectory_label_reviews.jsonl"
)).resolve()
REVIEW_LOCK_PATH = REVIEW_STORE_PATH.with_suffix(REVIEW_STORE_PATH.suffix + ".lock")

FILE_KINDS = {
    "model_patch": "model.patch",
    "evaluation_report": "evaluation/report.json",
    "test_output": "evaluation/test_output.txt",
    "run_manifest": "run_manifest.json",
    "agent_result": "agent_result.json",
    "agent_stdout": "agent_stdout.log",
}
MAX_FILE_BYTES = 2_000_000


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class DataRepository:
    def __init__(self) -> None:
        self.samples = read_jsonl(SAMPLE_PATH)
        self.sample_by_id = {r["annotation_id"]: r for r in self.samples}
        self.schema = read_json(SCHEMA_PATH, {})
        self.validator = Draft202012Validator(self.schema)
        self.canonical = {
            (r.get("model_label"), r.get("instance_id")): r
            for r in read_jsonl(OUTPUTS_DIR / "canonical_runs.jsonl")
        }
        self.auto_by_instance = self._group(OUTPUTS_DIR / "automatic_labels.jsonl")
        self.revisions_by_instance = self._group(OUTPUTS_DIR / "revision_episodes.jsonl")
        self.feedback_by_instance = self._group(OUTPUTS_DIR / "feedback_events.jsonl")
        self.replay_instances = {
            r["instance_id"]: r
            for r in read_jsonl(REPLAY_DIR / "checkpoint_instance_analysis.jsonl")
        }
        self.transitions_by_instance = self._group(
            REPLAY_DIR / "checkpoint_transition_analysis.jsonl", model_key=False
        )
        self.alignments_by_instance = self._group(
            REPLAY_DIR / "revision_replay_alignment.jsonl", model_key=False
        )
        self.summary = {
            "sample": read_json(DATA_DIR / "annotation_sample_summary.json", {}),
            "cleaning": read_json(OUTPUTS_DIR / "cleaning_summary.json", {}),
            "revision": read_json(OUTPUTS_DIR / "revision_summary.json", {}),
            "replay": read_json(REPLAY_DIR / "checkpoint_analysis_summary.json", {}),
            "alignment": read_json(REPLAY_DIR / "revision_replay_alignment_summary.json", {}),
        }

    @staticmethod
    def _group(path: Path, model_key: bool = True) -> dict[Any, list[dict[str, Any]]]:
        grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for row in read_jsonl(path):
            key = ((row.get("model_label"), row.get("instance_id"))
                   if model_key else row.get("instance_id"))
            grouped[key].append(row)
        return grouped

    def resolve_run_dir(self, sample: dict[str, Any]) -> Path | None:
        raw_value = sample.get("run_dir")
        raw = Path(raw_value) if raw_value else None
        if raw is not None and raw.is_dir():
            return raw
        if not TRAJECTORY_ROOT:
            return None
        relpath = sample.get("run_relpath")
        if relpath:
            candidate = TRAJECTORY_ROOT / relpath
            if candidate.is_dir():
                return candidate
        # Compatibility with unsanitized local datasets.
        parts = raw.parts if raw is not None else ()
        try:
            idx = parts.index("swebench_verified")
            candidate = TRAJECTORY_ROOT.joinpath(*parts[idx + 1:])
            if candidate.is_dir():
                return candidate
        except ValueError:
            pass
        return None

    def load_reviews(self) -> list[dict[str, Any]]:
        return read_jsonl(REVIEW_STORE_PATH)

    def reviews_by_sample(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self.load_reviews():
            result[row.get("annotation_id")].append(row)
        return result

    @staticmethod
    def _write_rows_locked(path: Path, lock_path: Path, rows: list[dict[str, Any]], prefix: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".jsonl", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    for row in rows:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                os.replace(tmp_name, path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def save_review(self, annotation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if annotation_id not in self.sample_by_id:
            raise KeyError("Unknown annotation_id")
        annotator = str(payload.get("annotator", "")).strip()
        verdict = str(payload.get("trajectory_verdict", "")).strip()
        allowed = set(self.schema.get("properties", {}).get("trajectory_verdict", {}).get("enum", []))
        if not annotator:
            raise ValueError("annotator: must not be empty")
        if verdict not in allowed:
            raise ValueError("trajectory_verdict: invalid option")
        sample = self.sample_by_id[annotation_id]
        suggestion = self.primary_suggestion(sample)
        doc = {
            "annotation_id": annotation_id,
            "annotator": annotator,
            "model_label": sample.get("model_label"),
            "instance_id": sample.get("instance_id"),
            "task_outcome": sample.get("task_outcome"),
            "trajectory_verdict": verdict,
            "accepted_suggestion": bool(suggestion and suggestion.get("value") == verdict),
            "machine_suggestion": suggestion,
            "notes": str(payload.get("notes", "")),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        rows = self.load_reviews()
        replaced = False
        for i, row in enumerate(rows):
            if row.get("annotation_id") == annotation_id and row.get("annotator") == annotator:
                rows[i] = doc
                replaced = True
                break
        if not replaced:
            rows.append(doc)
        self._write_rows_locked(REVIEW_STORE_PATH, REVIEW_LOCK_PATH, rows, "trajectory_reviews.")
        return doc

    def compact_item(self, sample: dict[str, Any], saved: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        key = (sample["model_label"], sample["instance_id"])
        replay = self.replay_instances.get(sample["instance_id"])
        annotations = saved.get(sample["annotation_id"], [])
        return {
            **{k: sample.get(k) for k in (
                "annotation_id", "instance_id", "repo", "model_label", "task_outcome",
                "official_resolved", "agent_task_status", "false_accept", "false_reject",
                "integrity_status", "tool_calls", "unique_states", "revision_episode_count",
                "sampling_stratum", "priority_score", "difficulty",
            )},
            "automatic_labels": [r.get("automatic_label") for r in self.auto_by_instance.get(key, [])],
            "has_replay": replay is not None,
            "replay_group": replay.get("replay_group") if replay else None,
            "annotation_count": len(annotations),
            "annotators": [r.get("annotator") for r in annotations],
            "is_annotated": bool(annotations),
        }

    def detail(self, annotation_id: str) -> dict[str, Any]:
        sample = self.sample_by_id[annotation_id]
        key = (sample["model_label"], sample["instance_id"])
        run_dir = self.resolve_run_dir(sample)
        file_status = {}
        if run_dir:
            for kind, rel in FILE_KINDS.items():
                p = run_dir / rel
                file_status[kind] = {"exists": p.is_file(), "size": p.stat().st_size if p.is_file() else 0}
            trajectory = run_dir / "trajectory.jsonl"
            file_status["trajectory"] = {
                "exists": trajectory.is_file(), "size": trajectory.stat().st_size if trajectory.is_file() else 0
            }
        return {
            "sample": sample,
            "canonical": self.canonical.get(key),
            "automatic_labels": self.auto_by_instance.get(key, []),
            "revisions": self.revisions_by_instance.get(key, []),
            "feedback": self.feedback_by_instance.get(key, []),
            "replay_instance": self.replay_instances.get(sample["instance_id"]),
            "replay_transitions": self.transitions_by_instance.get(sample["instance_id"], []),
            "replay_alignments": self.alignments_by_instance.get(sample["instance_id"], []),
            "reviews": self.reviews_by_sample().get(annotation_id, []),
            "run_dir": str(run_dir) if run_dir else None,
            "run_dir_original": sample.get("run_relpath") or sample.get("run_dir"),
            "files": file_status,
            "tool_statistics": self.tool_statistics(annotation_id),
            "suggestions": self.suggestions(sample),
            "primary_suggestion": self.primary_suggestion(sample),
        }

    def suggestions(self, sample: dict[str, Any]) -> dict[str, Any]:
        """Evidence-backed suggestions using values from the manual schema only.

        Suggestions are advisory and never persisted automatically. Episode-level
        revision verdicts prefer official replay alignment over automatic triage.
        """
        key = (sample["model_label"], sample["instance_id"])
        trajectory: list[dict[str, Any]] = []
        episodes: list[dict[str, Any]] = []

        def add(target: list[dict[str, Any]], field: str, value: str,
                confidence: float, reason: str, source: str,
                episode_id: str | None = None) -> None:
            target.append({
                "field": field,
                "value": value,
                "confidence": confidence,
                "reason": reason,
                "source": source,
                "episode_id": episode_id,
            })

        # Strong trajectory-level facts.
        if sample.get("integrity_status") == "suspect":
            add(trajectory, "trajectory_verdict", "Provenance Invalid", 0.98,
                "该轨迹的 integrity_status 为 suspect，不能做正常行为归因。",
                "canonical integrity audit")
            add(trajectory, "dominant_failure_stage", "provenance", 0.98,
                "主要风险来自轨迹归属或来源可信度。",
                "canonical integrity audit")
        elif sample.get("false_accept"):
            add(trajectory, "trajectory_verdict", "False Accept", 0.99,
                "Agent/Evaluator 内部接受或声称成功，但官方结果为 unresolved。",
                "agent task status + official evaluation")
        elif sample.get("false_reject"):
            add(trajectory, "trajectory_verdict", "False Reject", 0.99,
                "Agent/Evaluator 内部判定失败或 impossible，但官方结果为 resolved。",
                "agent task status + official evaluation")
        elif sample.get("official_resolved") and sample.get("tool_calls", 0) <= 20:
            add(trajectory, "trajectory_verdict", "Healthy Success", 0.72,
                "官方 resolved 且整条轨迹工具调用较少；仍需人工确认诊断和验证是否健康。",
                "official evaluation + trajectory cost")

        feedback_rows = self.feedback_by_instance.get(key, [])
        relevant_feedback = [r for r in feedback_rows if r.get("model_label") == sample["model_label"]]
        if relevant_feedback and all(r.get("status") == "protocol_failure" for r in relevant_feedback):
            add(trajectory, "feedback_quality", "protocol_failure", 0.99,
                "该轨迹的所有 Evaluator feedback 均未通过协议校验。",
                "feedback_events")
            if not sample.get("official_resolved"):
                add(trajectory, "trajectory_verdict", "Protocol Failure", 0.90,
                    "官方未解决，且每轮 Evaluator 都因协议失败，协议问题主导终止。",
                    "feedback_events + official evaluation")
                add(trajectory, "dominant_failure_stage", "feedback", 0.86,
                    "Evaluator 未产生有效结构化反馈，反馈环节是主要可见失败点。",
                    "feedback_events")
                add(trajectory, "harness_addressable", "yes", 0.82,
                    "协议与反馈控制属于 Harness 可直接改进的部分。",
                    "feedback_events")

        alignments = ({
            r.get("episode_id"): r
            for r in self.alignments_by_instance.get(sample["instance_id"], [])
        } if sample["model_label"] == "claude" else {})
        auto_rows = {
            r.get("episode_id"): r
            for r in self.auto_by_instance.get(key, [])
        }
        revision_rows = self.revisions_by_instance.get(key, [])
        replay_to_manual = {
            "Productive Revision": ("Productive Revision", 0.98),
            "Outcome-neutral Revision": ("Futile Revision", 0.94),
            "Partial Improvement": ("Productive Revision", 0.82),
            "Partial Regression": ("Destructive Revision", 0.92),
            "No-op Revision": ("No-op Revision", 0.98),
            "Unverified Revision": ("Unverified Revision", 0.96),
            "Not Applicable": ("Not Applicable", 0.99),
        }
        auto_to_manual = {
            "No-op Revision": ("No-op Revision", 0.72),
            "Futile Revision": ("Futile Revision", 0.68),
            "Looping Revision": ("Looping Revision", 0.70),
            "Productive Revision": ("Productive Revision", 0.70),
        }
        for revision in revision_rows:
            episode_id = revision.get("episode_id")
            if not episode_id:
                continue
            status = revision.get("feedback_status")
            trigger_map = {
                "protocol_failure": ("protocol_failure", 0.99),
                "continue": ("evaluator_feedback", 0.88),
                "reject": ("evaluator_feedback", 0.90),
                "blocked": ("environment", 0.65),
            }
            if status in trigger_map:
                value, confidence = trigger_map[status]
                add(episodes, "revision_trigger", value, confidence,
                    f"该 Episode 的 feedback_status 为 {status}。",
                    "revision_episodes.feedback_status", episode_id)

            alignment = alignments.get(episode_id)
            if alignment and alignment.get("replay_label") in replay_to_manual:
                replay_label = alignment["replay_label"]
                value, confidence = replay_to_manual[replay_label]
                state_changes = alignment.get("worker_state_change_count")
                # Outcome-neutral with no state change is more accurately No-op.
                if replay_label == "Outcome-neutral Revision" and not state_changes:
                    value, confidence = "No-op Revision", 0.96
                reason_map = {
                    "Productive Revision": "官方 Replay 显示该状态变化从 unresolved 跨越到 resolved。",
                    "Outcome-neutral Revision": "官方 Replay 显示修改前后 F2P/P2P 完全不变。",
                    "Partial Improvement": "官方 Replay 显示部分测试改善，但尚未完全 resolved。",
                    "Partial Regression": "官方 Replay 显示部分测试变差或出现副作用。",
                    "No-op Revision": "对齐结果显示没有产生新的 Worker 修订状态。",
                    "Unverified Revision": f"Replay 对齐状态为 {alignment.get('alignment_status')}，缺少可比较的前后官方状态。",
                    "Not Applicable": "Feedback 后没有下一轮 Worker 修订，因此不适用 Revision 结果标签。",
                }
                add(episodes, "revision_verdict", value, confidence,
                    reason_map[replay_label],
                    f"checkpoint replay: {replay_label}", episode_id)
            else:
                auto = auto_rows.get(episode_id, {}).get("automatic_label")
                if auto in auto_to_manual:
                    value, confidence = auto_to_manual[auto]
                    add(episodes, "revision_verdict", value, confidence,
                        "没有可比较 Replay；该建议仅来自自动初筛，需要人工核对。",
                        f"automatic triage: {auto}", episode_id)
                elif not revision.get("worker_revision"):
                    add(episodes, "revision_verdict", "Not Applicable", 0.96,
                        "该 Feedback 后没有下一轮 Worker 修订。",
                        "revision_episodes", episode_id)

        return {"trajectory": trajectory, "episodes": episodes}

    def primary_suggestion(self, sample: dict[str, Any]) -> dict[str, Any]:
        suggestions = self.suggestions(sample)
        verdicts = [x for x in suggestions.get("trajectory", []) if x.get("field") == "trajectory_verdict"]
        priority = {
            "Provenance Invalid": 100, "False Accept": 95, "False Reject": 95,
            "Protocol Failure": 90, "Environment Failure": 85,
            "Verification Failure": 80, "Looping Failure": 75,
            "Recovered Success": 70, "Costly Success": 65,
            "Healthy Success": 60, "Non-addressable Failure": 50,
            "Uncertain": 0,
        }
        if verdicts:
            return sorted(verdicts, key=lambda x: (priority.get(x.get("value"), 10), x.get("confidence", 0)), reverse=True)[0]

        key = (sample["model_label"], sample["instance_id"])
        auto = [r.get("automatic_label") for r in self.auto_by_instance.get(key, [])]
        if sample.get("official_resolved"):
            if sample.get("revision_episode_count", 0) >= 2 or sample.get("tool_calls", 0) > 33:
                return {"field": "trajectory_verdict", "value": "Costly Success", "confidence": 0.68,
                        "reason": "官方 resolved，但存在多轮修订或较高工具调用成本。", "source": "official evaluation + trajectory cost", "episode_id": None}
            return {"field": "trajectory_verdict", "value": "Healthy Success", "confidence": 0.66,
                    "reason": "官方 resolved，且没有发现更强的失败型证据。", "source": "official evaluation", "episode_id": None}
        if "Looping Revision" in auto:
            return {"field": "trajectory_verdict", "value": "Looping Failure", "confidence": 0.72,
                    "reason": "官方 unresolved，自动初筛发现重复绕圈修订。", "source": "automatic triage + official evaluation", "episode_id": None}
        return {"field": "trajectory_verdict", "value": "Uncertain", "confidence": 0.45,
                "reason": "现有结构化证据不足以可靠归入更具体的整条轨迹标签。", "source": "conservative fallback", "episode_id": None}

    def tool_statistics(self, annotation_id: str) -> dict[str, Any]:
        """Recount tool_execution records directly from the raw trajectory."""
        sample = self.sample_by_id[annotation_id]
        run_dir = self.resolve_run_dir(sample)
        path = run_dir / "trajectory.jsonl" if run_dir else None
        if not path or not path.is_file():
            return {"available": False, "total": None, "rounds": []}
        total = 0
        rounds: dict[Any, dict[str, Any]] = {}
        tool_names = Counter()
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("record_type") != "tool_execution":
                    continue
                total += 1
                round_id = row.get("round_id")
                agent = row.get("agent") or "unknown"
                tool = row.get("tool_name") or "unknown"
                entry = rounds.setdefault(round_id, {
                    "round_id": round_id, "total": 0, "worker": 0,
                    "evaluator": 0, "other": 0, "tool_names": Counter(),
                })
                entry["total"] += 1
                if agent == "WorkerAgent":
                    entry["worker"] += 1
                elif agent == "EvaluatorAgent":
                    entry["evaluator"] += 1
                else:
                    entry["other"] += 1
                entry["tool_names"][tool] += 1
                tool_names[tool] += 1
        output_rounds = []
        for round_id, entry in sorted(rounds.items(), key=lambda x: (x[0] is None, x[0] or 0)):
            entry = dict(entry)
            entry["tool_names"] = dict(entry["tool_names"])
            entry["phase"] = "初始解题" if round_id == 1 else f"第{round_id - 1}次反馈后的修订"
            output_rounds.append(entry)
        expected = sample.get("tool_calls")
        return {
            "available": True, "total": total, "expected_total": expected,
            "matches_sample_total": expected is None or total == expected,
            "worker_total": sum(x["worker"] for x in output_rounds),
            "evaluator_total": sum(x["evaluator"] for x in output_rounds),
            "other_total": sum(x["other"] for x in output_rounds),
            "tool_names": dict(tool_names), "rounds": output_rounds,
        }

    @staticmethod
    def _short_text(value: Any, limit: int = 360) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        value = " ".join(value.split())
        return value if len(value) <= limit else value[:limit - 1] + "…"

    def _tool_digest(self, row: dict[str, Any]) -> dict[str, Any]:
        name = row.get("tool_name") or "unknown"
        tool_input = row.get("tool_input") if isinstance(row.get("tool_input"), dict) else {}
        description = tool_input.get("description")
        if description:
            purpose = str(description)
        elif name == "Read":
            purpose = f"读取文件 {tool_input.get('file_path', '未知路径')}"
        elif name == "Edit":
            purpose = f"修改文件 {tool_input.get('file_path', '未知路径')}"
        elif name == "Grep":
            purpose = f"在 {tool_input.get('path', '代码库')} 搜索 {tool_input.get('pattern', '')}"
        elif name == "Bash":
            purpose = f"执行命令：{self._short_text(tool_input.get('command', ''), 180)}"
        else:
            purpose = f"调用 {name}：{self._short_text(tool_input, 180)}"

        changes = row.get("code_changes") if isinstance(row.get("code_changes"), dict) else {}
        changed_files = [
            item.get("path") for item in changes.get("changed_files") or []
            if isinstance(item, dict) and item.get("path")
        ]
        changed = bool(changes.get("before_tree") and changes.get("after_tree")
                       and changes.get("before_tree") != changes.get("after_tree"))
        if row.get("error"):
            result = self._short_text(row.get("error"), 360)
        else:
            response = row.get("tool_response")
            if isinstance(response, dict) and response.get("preview"):
                result = self._short_text(response.get("preview"), 360)
            elif response:
                result = self._short_text(response, 360)
            elif row.get("outcome") == "success":
                result = "执行成功，但结构化日志没有保存详细输出。"
            else:
                result = "未记录工具返回内容。"
        if row.get("outcome") == "failure":
            effect = "调用失败，没有直接产生有效结果。"
        elif changed:
            effect = f"产生代码变化，涉及 {len(changed_files)} 个文件。"
        else:
            effect = "调用成功，主要用于读取、搜索或验证，没有改变代码状态。"
        return {
            "step_id": row.get("step_id"),
            "tool_use_id": row.get("tool_use_id"),
            "tool_name": name,
            "purpose": self._short_text(purpose, 280),
            "outcome": row.get("outcome") or "unknown",
            "result_summary": result,
            "code_changed": changed,
            "changed_files": changed_files,
            "effect_summary": effect,
            "duration_ms": row.get("duration_ms"),
        }

    def trajectory_round_summary(self, annotation_id: str) -> dict[str, Any]:
        sample = self.sample_by_id[annotation_id]
        key = (sample["model_label"], sample["instance_id"])
        run_dir = self.resolve_run_dir(sample)
        path = run_dir / "trajectory.jsonl" if run_dir else None
        if not path or not path.is_file():
            return {"available": False, "rounds": []}
        rows = []
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        alignment_by_round = {
            r.get("revision_round_id"): r
            for r in self.alignments_by_instance.get(sample["instance_id"], [])
            if sample["model_label"] == "claude" and r.get("revision_round_id") is not None
        }
        feedback_by_round = {
            r.get("round_id"): r
            for r in self.feedback_by_instance.get(key, [])
            if r.get("model_label") == sample["model_label"]
        }
        round_ids = sorted({r.get("round_id") for r in rows if isinstance(r.get("round_id"), int)})
        output = []
        for round_id in round_ids:
            agents = {}
            for agent in ("WorkerAgent", "EvaluatorAgent"):
                agent_rows = [r for r in rows if r.get("round_id") == round_id and r.get("agent") == agent]
                thoughts, texts, prompts, results = [], [], [], []
                tools = []
                for row in agent_rows:
                    if row.get("record_type") == "tool_execution":
                        tools.append(self._tool_digest(row))
                    elif row.get("record_type") == "message" and isinstance(row.get("message"), dict):
                        msg = row["message"]
                        if msg.get("type") in {"AgentPrompt", "WorkerPrompt"} and msg.get("prompt"):
                            prompts.append(self._short_text(msg.get("prompt"), 1200))
                        for block in msg.get("content") or []:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "thinking" and block.get("thinking"):
                                thoughts.append({"step_id": block.get("step_id"), "text": str(block["thinking"])})
                            elif block.get("type") == "text" and block.get("text"):
                                texts.append({"step_id": block.get("step_id"), "text": str(block["text"])})
                        if msg.get("type") == "ResultMessage":
                            results.append({
                                "step_id": msg.get("step_id"),
                                "status": msg.get("subtype") or ("error" if msg.get("is_error") else "completed"),
                                "result": self._short_text(msg.get("result"), 1200),
                                "errors": msg.get("errors") or [],
                                "num_turns": msg.get("num_turns"),
                            })
                agents[agent] = {
                    "tool_count": len(tools),
                    "successful_tools": sum(t["outcome"] == "success" for t in tools),
                    "failed_tools": sum(t["outcome"] == "failure" for t in tools),
                    "code_change_tools": sum(t["code_changed"] for t in tools),
                    "changed_files": sorted({f for t in tools for f in t["changed_files"]}),
                    "prompts": prompts,
                    "thoughts": thoughts,
                    "texts": texts,
                    "results": results,
                    "tools": tools,
                }

            alignment = alignment_by_round.get(round_id)
            if round_id == 1:
                utility = {
                    "label": "Initial Round",
                    "summary": "这是初始解题轮，没有前一轮修订状态可直接比较；最终效果需结合后续 Replay 和官方评测。",
                    "confidence": "context",
                }
            elif alignment:
                replay_label = alignment.get("replay_label")
                summary_map = {
                    "Outcome-neutral Revision": "官方 Replay 显示本轮前后 F2P/P2P 完全不变：代码有变化，但任务效用没有改善。",
                    "Productive Revision": "官方 Replay 显示本轮从 unresolved 变为 resolved，修订有效。",
                    "Partial Improvement": "官方 Replay 显示部分测试改善，但任务仍未完全解决。",
                    "Partial Regression": "官方 Replay 显示部分测试变差或出现副作用。",
                    "Unverified Revision": f"缺少可比较的官方前后状态（{alignment.get('alignment_status')}），无法确认本轮效果。",
                    "No-op Revision": "本轮没有产生新的可评测代码状态。",
                    "Not Applicable": "没有后续 Worker 修订，不适用效果判断。",
                }
                utility = {"label": replay_label, "summary": summary_map.get(replay_label, replay_label), "confidence": "official_replay"}
            else:
                utility = {"label": "No Replay Evidence", "summary": "本轮没有可用的官方 Replay 对照，只能根据代码变化和测试日志人工判断。", "confidence": "limited"}

            feedback = feedback_by_round.get(round_id)
            output.append({
                "round_id": round_id,
                "phase": "初始解题与评估" if round_id == 1 else f"第{round_id - 1}次反馈后的修订与评估",
                "worker": agents["WorkerAgent"],
                "evaluator": agents["EvaluatorAgent"],
                "feedback": ({
                    "status": feedback.get("status"),
                    "assessment": feedback.get("assessment"),
                    "next_worker_prompt": feedback.get("next_worker_prompt"),
                    "protocol_valid": feedback.get("protocol_valid"),
                } if feedback else None),
                "utility": utility,
            })
        return {"available": True, "rounds": output, "official_outcome": sample.get("task_outcome")}

    def trajectory_digest(self, annotation_id: str) -> dict[str, Any]:
        sample = self.sample_by_id[annotation_id]
        run_dir = self.resolve_run_dir(sample)
        if not run_dir or not (run_dir / "trajectory.jsonl").is_file():
            return {"available": False, "records": [], "problem_statement": None}
        path = run_dir / "trajectory.jsonl"
        records, problem, counts = [], None, Counter()
        groups = Counter()
        with path.open(encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, 1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                typ = row.get("record_type", "unknown")
                counts[typ] += 1
                if typ == "session" and not problem:
                    problem = row.get("original_prompt")
                # The opening session record repeats the whole problem statement. It is
                # represented separately above; retain only the completed termination.
                if typ == "session" and not row.get("completed"):
                    continue
                if typ not in {"message", "tool_execution", "runtime_event", "evaluation", "session"}:
                    continue
                item = dict(row)
                item["line_no"] = line_no
                if typ == "session" and row.get("completed"):
                    item["display_type"] = "termination"
                elif typ == "message":
                    msg = row.get("message") if isinstance(row.get("message"), dict) else {}
                    item["display_type"] = msg.get("type") or "message"
                else:
                    item["display_type"] = typ
                groups[(row.get("round_id"), row.get("agent") or "System")] += 1
                records.append(item)
        summary = self.trajectory_round_summary(annotation_id)
        return {
            "available": True,
            "path": str(path),
            "round_summary": summary.get("rounds", []),
            "counts": dict(counts),
            "problem_statement": problem,
            "records": records,
            "record_count": len(records),
            "groups": [
                {"round_id": round_id, "agent": agent, "count": count}
                for (round_id, agent), count in groups.items()
            ],
        }



repo = DataRepository()
app = Flask(__name__, template_folder="templates", static_folder="static")
app.json.ensure_ascii = False


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/bootstrap")
def bootstrap() -> Response:
    props = repo.schema.get("properties", {})
    enums = {k: v.get("enum", []) for k, v in props.items() if "enum" in v}
    reviews = repo.reviews_by_sample()
    annotated = sum(bool(reviews.get(s["annotation_id"])) for s in repo.samples)
    annotators = Counter(a.get("annotator") for rows in reviews.values() for a in rows)
    return jsonify({
        "total": len(repo.samples), "annotated_samples": annotated,
        "annotation_records": sum(len(x) for x in reviews.values()),
        "annotators": annotators, "enums": enums, "summary": repo.summary,
        "store_path": str(REVIEW_STORE_PATH),
        "annotation_mode": "single_label_review",
    })


@app.get("/api/items")
def items() -> Response:
    reviews = repo.reviews_by_sample()
    rows = [repo.compact_item(s, reviews) for s in repo.samples]
    q = request.args.get("q", "").strip().lower()
    model = request.args.get("model", "")
    outcome = request.args.get("outcome", "")
    status = request.args.get("status", "")
    replay = request.args.get("replay", "")
    stratum = request.args.get("stratum", "")
    if q:
        rows = [r for r in rows if q in " ".join(str(r.get(k, "")) for k in
                ("annotation_id", "instance_id", "repo", "sampling_stratum")).lower()]
    if model: rows = [r for r in rows if r["model_label"] == model]
    if outcome: rows = [r for r in rows if r["task_outcome"] == outcome]
    if status == "annotated": rows = [r for r in rows if r["is_annotated"]]
    if status == "pending": rows = [r for r in rows if not r["is_annotated"]]
    if replay == "yes": rows = [r for r in rows if r["has_replay"]]
    if replay == "no": rows = [r for r in rows if not r["has_replay"]]
    if stratum: rows = [r for r in rows if r["sampling_stratum"] == stratum]
    rows.sort(key=lambda r: (-int(r.get("priority_score") or 0), r["annotation_id"]))
    return jsonify({"items": rows, "count": len(rows)})


@app.get("/api/items/<annotation_id>")
def item_detail(annotation_id: str) -> Response:
    if annotation_id not in repo.sample_by_id:
        return jsonify({"error": "not found"}), 404
    return jsonify(repo.detail(annotation_id))


@app.get("/api/items/<annotation_id>/trajectory")
def trajectory(annotation_id: str) -> Response:
    if annotation_id not in repo.sample_by_id:
        return jsonify({"error": "not found"}), 404
    return jsonify(repo.trajectory_digest(annotation_id))


@app.get("/api/items/<annotation_id>/file/<kind>")
def item_file(annotation_id: str, kind: str) -> Response:
    if annotation_id not in repo.sample_by_id or kind not in FILE_KINDS:
        return jsonify({"error": "not found"}), 404
    run_dir = repo.resolve_run_dir(repo.sample_by_id[annotation_id])
    path = run_dir / FILE_KINDS[kind] if run_dir else None
    if not path or not path.is_file():
        return jsonify({"error": "file unavailable"}), 404
    data = path.read_bytes()[:MAX_FILE_BYTES]
    truncated = path.stat().st_size > MAX_FILE_BYTES
    text = data.decode("utf-8", errors="replace")
    return jsonify({"kind": kind, "path": str(path), "size": path.stat().st_size,
                    "truncated": truncated, "content": text})


@app.post("/api/reviews/<annotation_id>")
def save_review(annotation_id: str) -> Response:
    try:
        doc = repo.save_review(annotation_id, request.get_json(force=True) or {})
        return jsonify({"ok": True, "review": doc})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/export")
def export_annotations() -> Response:
    if not REVIEW_STORE_PATH.exists():
        return jsonify({"error": "No trajectory label reviews saved yet"}), 404
    return send_file(REVIEW_STORE_PATH, as_attachment=True, download_name="trajectory_label_reviews.jsonl")


@app.get("/health")
def health() -> Response:
    return jsonify({"ok": True, "sample_count": len(repo.samples)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
