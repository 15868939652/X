from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


GLOBAL_IDLE = "IDLE"
GLOBAL_RUNNING = "RUNNING"
GLOBAL_PAUSED = "PAUSED"
GLOBAL_COMPLETED = "COMPLETED"
GLOBAL_FAILED = "FAILED"

TASK_PENDING = "PENDING"
TASK_RUNNING = "RUNNING"
TASK_SUCCESS = "SUCCESS"
TASK_FAILED = "FAILED"


@dataclass
class TaskError:
    type: str
    message: str
    suggestion: str


@dataclass
class Task:
    id: str
    platform: str
    status: str = TASK_PENDING
    score: float = -1
    content: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    base_keyword: str = ""
    keyword: str = ""
    title: str = ""
    article_path: str = ""
    stage: str = "等待执行"
    retries: int = 0
    passed: bool | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: list[dict] = field(default_factory=list)
    failed_stage: str = ""
    failure_reason: str = ""
    summary: str = "尚未开始"
    events: list[str] = field(default_factory=list)
    platform_index: int = 1

    def recommendation(self) -> str:
        if self.status == TASK_FAILED:
            return "建议重试"
        if self.score >= 90:
            return "推荐发布"
        if self.score >= 70:
            return "可用"
        if self.score >= 0:
            return "建议重写"
        return "待完成"

    def recommendation_color(self) -> str:
        mapping = {
            "推荐发布": "#15803D",
            "可用": "#1D4ED8",
            "建议重写": "#C27A14",
            "建议重试": "#C24141",
            "待完成": "#64748B",
        }
        return mapping[self.recommendation()]
