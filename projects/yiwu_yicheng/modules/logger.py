"""
Baseline 日志系统。

每篇文章对应一条 JSONL 记录，包含：
- 生成参数（mode/profile/style/trigger）
- 初稿/去AI后/最终 三次快照的得分和长度
- 每次 LLM 调用的模型和 token 消耗
- 人工标注占位字段

线程安全：通过 threading.local 让每个生成任务有自己独立的 call bucket；
         写 JSONL 用全局 Lock 串行化。
"""

import json
import os
import threading
from datetime import datetime
from typing import Optional

_local = threading.local()
_write_lock = threading.Lock()
_log_file_path: Optional[str] = None


def init_session():
    """在 main.run() 开头调用一次，决定本次运行写到哪个 JSONL 文件。"""
    global _log_file_path
    os.makedirs("logs", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file_path = os.path.join("logs", f"generation_{stamp}.jsonl")
    return _log_file_path


def get_log_path() -> Optional[str]:
    return _log_file_path


# ========================= LLM 调用收集 =========================

def start_task_bucket():
    """每个任务（process_task）开头调用，开启一个新的调用收集桶。"""
    _local.bucket = []


def record_llm_call(tier: str, model: str, prompt_tokens: Optional[int],
                    completion_tokens: Optional[int], error: Optional[str] = None):
    """llm.py 内部调用，把本次调用的 usage 写入当前线程的桶。"""
    bucket = getattr(_local, "bucket", None)
    if bucket is None:
        return
    bucket.append({
        "tier": tier,  # "pro" or "lite"
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "error": error,
    })


def get_task_calls() -> list:
    return list(getattr(_local, "bucket", []) or [])


def end_task_bucket():
    _local.bucket = None


# ========================= 记录写入 =========================

def write_record(record: dict):
    """追加一条任务记录到 JSONL。"""
    if _log_file_path is None:
        return  # session 未初始化，静默跳过（如单元测试场景）
    line = json.dumps(record, ensure_ascii=False)
    with _write_lock:
        with open(_log_file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
