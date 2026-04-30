import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config import BATCH_SIZE, BRAND, CONCURRENT_WORKERS, OUTPUT_PER_KEYWORD
from modules import logger
from modules.generator import generate_article
from modules.keyword import expand_one
from modules.profile_loader import get_active_profile
from modules.progress import (
    console,
    show_article_header,
    show_done,
    show_error,
    show_header,
    show_saved,
    show_total,
    step,
)
from pathing import shared_prompt_path
from project_paths import PROJECT_ROOT as PROJECT_ROOT_PATH
from common.task_planner import build_task_specs

PROJECT_ROOT = str(PROJECT_ROOT_PATH)

_pause_file_path: str | None = None


def load_prompt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_article(platform: str, title: str, content: str, platform_index: int, meta: dict | None = None) -> str:
    date = datetime.now().strftime("%m%d")
    folder = os.path.join("output", date)
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"{platform}_{platform_index}.txt")

    header = ""
    if meta:
        lines = ["<!-- baseline meta"]
        for key in ("mode", "platform", "profile", "style", "trigger", "first_draft_score", "final_score", "retries", "passed"):
            if key in meta:
                lines.append(f"{key}: {meta[key]}")
        lines.append("annotation: ai_taste=?/10 structure_ok=? publishable=? notes=")
        lines.append("-->\n")
        header = "\n".join(lines) + "\n"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(header + f"{title}\n\n{content}")

    show_saved(filename)
    return filename


def _normalize_article_text(text: str) -> str:
    text = text.replace("公立医院", "综合性医院")
    text = text.replace("私立医院", "专科医院")
    return text


def process_task(task_id: int, base_keyword: str, platform: str, platform_index: int) -> None:
    if _pause_file_path and os.path.exists(_pause_file_path):
        return
    logger.start_task_bucket()
    start_ts = datetime.now()
    generation_mode = os.environ.get("X_GENERATION_MODE", "fast")

    try:
        with step(f"#{task_id} 扩展长尾词"):
            keyword = base_keyword if generation_mode == "one_shot" else expand_one(base_keyword)
        show_done(f"#{task_id} 长尾词", keyword)

        platform_prompt = load_prompt(shared_prompt_path("platform", f"{platform}.txt"))
        show_article_header(platform, keyword, task_id)
        title, article, gen_record = generate_article(
            keyword,
            platform,
            platform_prompt,
            generation_mode=generation_mode,
        )
        article = _normalize_article_text(article)

        article_path = None
        for _ in range(OUTPUT_PER_KEYWORD):
            article_path = save_article(platform, title, article, platform_index, meta=gen_record)

        if sys.stdout:
            short_title = (title[:40] + "...") if len(title) > 40 else title
            snippet = article[:180].replace("\n", " ")
            sys.stdout.write(f"[TITLE] {platform} | {short_title}\n")
            sys.stdout.write(f"[SNIPPET] {platform} | {snippet}...\n")
            sys.stdout.flush()

        record = {
            "task_id": task_id,
            "timestamp": start_ts.isoformat(timespec="seconds"),
            "duration_sec": (datetime.now() - start_ts).total_seconds(),
            "platform": platform,
            "base_keyword": base_keyword,
            "keyword": keyword,
            "article_path": article_path,
            "llm_calls": logger.get_task_calls(),
            "is_experiment": False,
            "experiment_success": False,
            "annotation": {
                "ai_taste": None,
                "structure_ok": None,
                "publishable": None,
                "notes": "",
            },
        }
        record.update(gen_record)
        logger.write_record(record)
    except Exception as exc:
        failure_record = {
            "task_id": task_id,
            "timestamp": start_ts.isoformat(timespec="seconds"),
            "platform": platform,
            "base_keyword": base_keyword,
            "keyword": locals().get("keyword", ""),
            "error": str(exc),
            "llm_calls": logger.get_task_calls(),
        }
        partial_record = getattr(exc, "partial_record", None)
        if isinstance(partial_record, dict):
            failure_record.update(partial_record)
        logger.write_record(failure_record)
        raise
    finally:
        logger.end_task_bucket()


def _load_task_specs(profile: dict, platform_only: str, custom_count: int, platform_list: list[str] | None, task_specs: list[dict] | None) -> list[dict]:
    if task_specs is not None:
        return list(task_specs)

    task_total = custom_count if custom_count > 0 else BATCH_SIZE
    platforms = [key for key in ("zhihu", "sohu", "baijiahao", "toutiao")]
    if platform_list:
        platforms = [p for p in platform_list if p in platforms]
    elif platform_only:
        platforms = [platform_only]
    if not platforms:
        platforms = [key for key in ("zhihu", "sohu", "baijiahao", "toutiao")]

    keyword_file = profile.get("keyword_file")
    keyword_path = os.path.join(PROJECT_ROOT, keyword_file)
    return build_task_specs(profile, keyword_path, platforms, task_total)


def run(
    platform_only: str = "",
    custom_count: int = 0,
    platform_list: list[str] | None = None,
    concurrent_workers: int | None = None,
    task_specs: list[dict] | None = None,
    pause_file: str | None = None,
    generation_mode: str = "fast",
):
    global _pause_file_path
    _pause_file_path = pause_file
    os.environ["X_GENERATION_MODE"] = (generation_mode or "fast").strip().lower()
    profile = get_active_profile()
    tasks = _load_task_specs(profile, platform_only, custom_count, platform_list, task_specs)

    show_header(BRAND)
    log_path = logger.init_session()
    console.print(f"[dim]baseline 日志：{log_path}[/dim]")

    if not tasks:
        console.print("[red][ERR][/red] 任务计划为空，请检查关键词文件或筛选条件")
        return

    show_total(len(tasks))

    worker_count = concurrent_workers or CONCURRENT_WORKERS
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                process_task,
                int(task["task_id"]),
                task["base_keyword"],
                task["platform"],
                int(task["platform_index"]),
            ): (
                int(task["task_id"]),
                task["base_keyword"],
                task["platform"],
            )
            for task in tasks
        }
        for future in as_completed(futures):
            tid, kw, platform = futures[future]
            try:
                future.result()
            except Exception as exc:
                show_error(f"#{tid} {platform} / {kw[:20]} 失败：{exc}")

    console.print(f"\n[green][OK] 本次 baseline 日志已保存至：{log_path}[/green]")
    console.print(f"[dim]运行 python analyze.py {log_path} 查看统计[/dim]")


def cli():
    platform_only = ""
    platform_list = None
    custom_count = 0
    concurrent_workers = None
    plan_path = ""
    pause_file: str | None = None
    generation_mode = "fast"
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--platform" and i + 1 < len(args):
            platform_only = args[i + 1].strip()
            i += 2
        elif args[i] == "--platforms" and i + 1 < len(args):
            platform_list = [x.strip() for x in args[i + 1].split(",") if x.strip()]
            i += 2
        elif args[i] == "--count" and i + 1 < len(args):
            try:
                custom_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--workers" and i + 1 < len(args):
            try:
                concurrent_workers = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--plan" and i + 1 < len(args):
            plan_path = args[i + 1]
            i += 2
        elif args[i] == "--pause-file" and i + 1 < len(args):
            pause_file = args[i + 1]
            i += 2
        elif args[i] == "--generation-mode" and i + 1 < len(args):
            generation_mode = args[i + 1].strip()
            i += 2
        else:
            i += 1

    task_specs = None
    if plan_path:
        with open(plan_path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        task_specs = payload.get("tasks", [])
        custom_count = len(task_specs) or custom_count

    run(
        platform_only=platform_only,
        custom_count=custom_count,
        platform_list=platform_list,
        concurrent_workers=concurrent_workers,
        task_specs=task_specs,
        pause_file=pause_file,
        generation_mode=generation_mode,
    )
