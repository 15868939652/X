from __future__ import annotations

import json
import os
import re
from pathlib import Path

from launcher_core.models import (
    GLOBAL_COMPLETED,
    GLOBAL_FAILED,
    GLOBAL_IDLE,
    GLOBAL_PAUSED,
    GLOBAL_RUNNING,
    TASK_FAILED,
    TASK_PENDING,
    TASK_RUNNING,
    TASK_SUCCESS,
    Task,
)


class TaskManager:
    def __init__(self) -> None:
        self.global_state = GLOBAL_IDLE
        self.tasks: dict[str, Task] = {}
        self.task_order: list[str] = []
        self.plan_metadata: dict = {}

    def reset(self) -> None:
        self.global_state = GLOBAL_IDLE
        self.tasks = {}
        self.task_order = []
        self.plan_metadata = {}

    def start_batch(self, tasks: list[Task], metadata: dict | None = None) -> None:
        self.tasks = {task.id: task for task in tasks}
        self.task_order = [task.id for task in tasks]
        self.plan_metadata = metadata or {}
        self.global_state = GLOBAL_RUNNING

    def ordered_tasks(self) -> list[Task]:
        return [self.tasks[task_id] for task_id in self.task_order if task_id in self.tasks]

    def get_task(self, task_id: str | int) -> Task | None:
        return self.tasks.get(str(task_id))

    def counts(self) -> dict[str, int]:
        items = self.ordered_tasks()
        return {
            "total": len(items),
            "success": sum(task.status == TASK_SUCCESS for task in items),
            "failed": sum(task.status == TASK_FAILED for task in items),
            "running": sum(task.status == TASK_RUNNING for task in items),
            "pending": sum(task.status == TASK_PENDING for task in items),
        }

    def score_summary(self) -> dict[str, int]:
        items = [task for task in self.ordered_tasks() if task.status == TASK_SUCCESS]
        return {
            "excellent": sum(task.score >= 90 for task in items),
            "qualified": sum(70 <= task.score < 90 for task in items),
            "rewrite": sum(0 <= task.score < 70 for task in items),
        }

    def mark_paused(self) -> None:
        self.global_state = GLOBAL_PAUSED
        for task in self.ordered_tasks():
            if task.status == TASK_RUNNING:
                task.status = TASK_PENDING
                task.stage = "等待继续"
                task.summary = "已暂停，等待继续"
                self.add_event(task.id, "任务已暂停，等待继续")

    def mark_running(self) -> None:
        self.global_state = GLOBAL_RUNNING

    def mark_finished(self, success: bool) -> None:
        counts = self.counts()
        if success and counts["failed"] == 0:
            self.global_state = GLOBAL_COMPLETED
        elif success:
            self.global_state = GLOBAL_FAILED
        elif self.global_state != GLOBAL_PAUSED:
            self.global_state = GLOBAL_FAILED

    def pending_specs(self) -> list[dict]:
        specs = []
        for task in self.ordered_tasks():
            if task.status in {TASK_PENDING, TASK_RUNNING}:
                specs.append(self._task_to_spec(task))
        return specs

    def retry_spec(self, task_id: str | int) -> list[dict]:
        task = self.get_task(task_id)
        if not task:
            return []
        task.status = TASK_PENDING
        task.error = ""
        task.failed_stage = ""
        task.failure_reason = ""
        task.summary = "等待重试"
        task.stage = "等待执行"
        self.add_event(task.id, "已加入重试队列")
        return [self._task_to_spec(task)]

    def delete_task(self, task_id: str | int, remove_file: bool = False) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        if remove_file and task.article_path and os.path.exists(task.article_path):
            try:
                os.remove(task.article_path)
            except OSError:
                pass
        self.tasks.pop(task.id, None)
        self.task_order = [item for item in self.task_order if item != task.id]

    def export_task(self, task_id: str | int, export_dir: str | Path) -> str | None:
        task = self.get_task(task_id)
        if not task or not task.article_path or not os.path.exists(task.article_path):
            return None
        export_path = Path(export_dir)
        export_path.mkdir(parents=True, exist_ok=True)
        target = export_path / Path(task.article_path).name
        target.write_text(Path(task.article_path).read_text(encoding="utf-8"), encoding="utf-8")
        return str(target)

    def copy_text(self, task_id: str | int) -> str:
        task = self.get_task(task_id)
        if not task:
            return ""
        return f"{task.title}\n\n{task.content}".strip()

    def add_event(self, task_id: str | int, message: str) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        clean = re.sub(r"\s+", " ", message).strip()
        if clean and (not task.events or task.events[-1] != clean):
            task.events.append(clean)

    def apply_runtime_line(self, line: str) -> None:
        match = re.search(r"#(\d+)", line)
        if not match:
            return
        task = self.get_task(match.group(1))
        if not task:
            return
        if task.status == TASK_PENDING:
            task.status = TASK_RUNNING
            task.summary = "处理中"
        platform = self._extract_platform(line)
        if platform:
            task.platform = platform
        keyword_match = re.search(r"\[bright_blue\]\w+\[/bright_blue\]\s+\[dim\]-\[/dim\]\s+(.+?)\s+\[dim\]-\[/dim\]\s+#", line)
        if keyword_match:
            task.keyword = keyword_match.group(1).strip()
        stage = self._extract_stage(line)
        if stage:
            task.stage = stage
        if "失败" in line or "[ERR]" in line:
            task.status = TASK_FAILED
            task.summary = "运行失败"
            task.error = line
        self.add_event(task.id, line)

    def apply_record(self, record: dict, project_dir: str) -> Task | None:
        task = self.get_task(record.get("task_id", ""))
        if not task:
            return None
        task.platform = record.get("platform", task.platform)
        task.base_keyword = record.get("base_keyword", task.base_keyword)
        task.keyword = record.get("keyword", task.keyword)
        task.title = record.get("title", task.title)
        task.retries = int(record.get("retries", task.retries or 0) or 0)
        task.llm_calls = record.get("llm_calls", task.llm_calls or [])
        task.prompt_tokens = sum((item.get("prompt_tokens") or 0) for item in task.llm_calls)
        task.completion_tokens = sum((item.get("completion_tokens") or 0) for item in task.llm_calls)
        task.failed_stage = record.get("failed_stage", task.failed_stage)
        task.failure_reason = record.get("failure_reason", task.failure_reason)
        task.passed = record.get("passed", task.passed)
        if record.get("article_path"):
            task.article_path = str(Path(project_dir) / record["article_path"])
            task.content = self._read_content(task.article_path)
            if not task.title and task.content:
                task.title = task.content.splitlines()[0].strip()

        if record.get("error"):
            task.status = TASK_FAILED
            task.error = record["error"]
            task.stage = self.failure_stage_label(task.failed_stage)
            task.summary = f"失败 · {task.stage}"
            self.add_event(task.id, f"失败原因：{task.failure_reason or task.error}")
            return task

        task.score = float(record.get("final_score", task.score))
        task.status = TASK_SUCCESS
        task.stage = "保存完成"
        task.summary = f"完成 · {int(task.score) if task.score >= 0 else '--'} 分 · {task.recommendation()}"
        self.add_event(task.id, task.summary)
        return task

    def build_batch_report(self) -> str:
        counts = self.score_summary()
        total = self.counts()["total"]
        return f"优秀 {counts['excellent']} · 合格 {counts['qualified']} · 需优化 {counts['rewrite']} · 总任务 {total}"

    def recommendation_lines(self) -> list[str]:
        lines = []
        for task in self.ordered_tasks():
            lines.append(f"{task.id} · {task.platform} · {task.recommendation()}")
        return lines

    @staticmethod
    def failure_stage_label(failed_stage: str) -> str:
        return {
            "draft_generation": "首稿生成",
            "first_score": "初稿评分",
            "final_score": "终稿评分",
            "retry_score": "重评分",
        }.get(failed_stage or "", "任务失败")

    @staticmethod
    def _extract_platform(line: str) -> str:
        lower = line.lower()
        for key in ("zhihu", "sohu", "baijiahao", "toutiao"):
            if key in lower:
                return key
        return ""

    @staticmethod
    def _extract_stage(line: str) -> str:
        mapping = {
            "扩展长尾词": "关键词扩展",
            "长尾词": "关键词扩展",
            "初稿完成": "首稿生成",
            "去AI化完成": "去AI化",
            "质量评分": "评分",
            "重新评分": "评分",
            "[SAVE]": "保存",
        }
        for key, value in mapping.items():
            if key in line:
                return value
        return ""

    @staticmethod
    def _read_content(article_path: str) -> str:
        if not article_path or not os.path.exists(article_path):
            return ""
        try:
            text = Path(article_path).read_text(encoding="utf-8")
        except Exception:
            return ""
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
        return text

    @staticmethod
    def _task_to_spec(task: Task) -> dict:
        return {
            "task_id": int(task.id),
            "base_keyword": task.base_keyword,
            "platform": task.platform,
            "platform_index": task.platform_index,
        }
