import os
import random
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import bootstrap_shared
import pandas as pd

from config import BRAND, OUTPUT_PER_KEYWORD, CONCURRENT_WORKERS, BATCH_SIZE, GENERATOR_PROVIDER
from modules.profile_loader import get_active_profile
from pathing import shared_prompt_path
from modules.keyword import expand_one
from modules.generator import generate_article
from modules.progress import (
    console, show_header, show_total,
    show_article_header, show_saved, show_error, step, show_done,
)
from modules import logger
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def load_prompt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_article(platform: str, title: str, content: str, platform_index: int,
                 meta: dict = None) -> str:
    """保存文章。meta 以注释块形式写在文件顶部，便于人工标注时直接看到参数。
    返回文件路径。"""
    date = datetime.now().strftime("%m%d")
    folder = os.path.join("output", date)
    os.makedirs(folder, exist_ok=True)

    filename = os.path.join(folder, f"{platform}_{platform_index}.txt")

    header = ""
    if meta:
        lines = ["<!-- baseline meta"]
        for k in ("mode", "profile", "style", "trigger",
                  "first_draft_score", "final_score", "retries", "passed"):
            if k in meta:
                lines.append(f"{k}: {meta[k]}")
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
    """单篇生成任务，供线程池调用"""
    # 每个任务独立的 LLM 调用收集桶
    logger.start_task_bucket()
    start_ts = datetime.now()

    try:
        with step(f"#{task_id} 扩展长尾词"):
            keyword = expand_one(base_keyword)
        show_done(f"#{task_id} 长尾词", keyword)

        platform_prompt = load_prompt(shared_prompt_path("platform", f"{platform}.txt"))
        show_article_header(platform, keyword, task_id)
        title, article, gen_record = generate_article(keyword, platform, platform_prompt)
        article = _normalize_article_text(article)

        article_path = None
        for _ in range(OUTPUT_PER_KEYWORD):
            article_path = save_article(platform, title, article, platform_index, meta=gen_record)

        # 流式输出标题和内容片段
        short_title = (title[:40] + "…") if len(title) > 40 else title
        snippet = article[:180].replace("\n", " ")
        if sys.stdout:
            sys.stdout.write(f"[TITLE] {platform} | {short_title}\n")
            sys.stdout.write(f"[SNIPPET] {platform} | {snippet}…\n")
            sys.stdout.flush()

        # 汇总成一条 baseline 记录
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
                "ai_taste": None,       # 0-10，越高越像AI
                "structure_ok": None,   # True/False
                "publishable": None,    # True/False，最终能否发
                "notes": "",
            },
        }
        record.update(gen_record)
        logger.write_record(record)

    except Exception as e:
        logger.write_record({
            "task_id": task_id,
            "timestamp": start_ts.isoformat(timespec="seconds"),
            "platform": platform,
            "base_keyword": base_keyword,
            "error": str(e),
            "llm_calls": logger.get_task_calls(),
        })
        raise
    finally:
        logger.end_task_bucket()


def run(platform_only: str = "", custom_count: int = 0):
    profile = get_active_profile()
    brand = profile["brand"]
    task_total = custom_count if custom_count > 0 else BATCH_SIZE

    show_header(brand)
    log_path = logger.init_session()
    console.print(f"[dim]baseline 日志：{log_path}[/dim]")

    keyword_file = profile.get("keyword_file", "data/keywords/yiwu_yicheng.xlsx")
    keyword_path = os.path.join(PROJECT_ROOT, keyword_file)
    df = pd.read_excel(keyword_path)

    keyword_col = "keyword" if "keyword" in df.columns else df.columns[0]
    df[keyword_col] = (
        df[keyword_col]
        .astype(str)
        .str.strip()
    )
    df = df[df[keyword_col] != ""]
    df = df.drop_duplicates(subset=[keyword_col]).reset_index(drop=True)

    if "科室" not in df.columns:
        def classify_keyword(kw):
            kw = str(kw).lower()
            if any(word in kw for word in ["妇科", "白带", "月经", "人流", "备孕", "宫颈", "妇科检查"]):
                return "妇科"
            elif any(word in kw for word in ["皮肤", "痘痘", "皮炎", "湿疹", "痤疮", "毛囊炎", "激光", "光子"]):
                return "皮肤科"
            else:
                return "常规体检"
        df["科室"] = df[keyword_col].apply(classify_keyword)

    gyn_keywords = df[df["科室"] == "妇科"][keyword_col].dropna().tolist()
    derm_keywords = df[df["科室"] == "皮肤科"][keyword_col].dropna().tolist()
    exam_keywords = df[df["科室"] == "常规体检"][keyword_col].dropna().tolist()

    total = task_total
    gyn_count = max(1, int(total * 0.3))
    derm_count = max(1, int(total * 0.6))
    exam_count = max(1, total - gyn_count - derm_count)

    random.shuffle(gyn_keywords)
    random.shuffle(derm_keywords)
    random.shuffle(exam_keywords)

    def ensure_enough(keywords, count, category):
        if not keywords:
            return []
        if len(keywords) < count:
            while len(keywords) < count:
                keywords.extend(keywords[:count - len(keywords)])
        return keywords[:count]

    selected_gyn = ensure_enough(gyn_keywords, gyn_count, "妇科")
    selected_derm = ensure_enough(derm_keywords, derm_count, "皮肤科")
    selected_exam = ensure_enough(exam_keywords, exam_count, "常规体检")

    selected_kw = selected_gyn + selected_derm + selected_exam
    random.shuffle(selected_kw)

    platforms = ["zhihu", "sohu", "baijiahao", "toutiao"]
    if platform_only:
        platforms = [platform_only]
    per_platform = task_total if platform_only else max(1, task_total // len(platforms))
    total = per_platform * len(platforms)

    if not selected_kw:
        console.print("[red][ERR][/red] 关键词库为空，请检查 keyword 文件")
        return
    if len(selected_kw) < total:
        while len(selected_kw) < total:
            selected_kw.extend(selected_kw[:total - len(selected_kw)])
    selected_kw = selected_kw[:total]

    random.shuffle(selected_kw)
    platform_slots = []
    for platform in platforms:
        for platform_index in range(1, per_platform + 1):
            platform_slots.append((platform, platform_index))
    random.shuffle(platform_slots)

    tasks = []
    for task_id, ((platform, platform_index), keyword) in enumerate(zip(platform_slots, selected_kw), start=1):
        tasks.append((task_id, keyword, platform, platform_index))

    show_total(len(tasks))

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = {
            executor.submit(process_task, tid, kw, p, p_idx): (tid, kw, p)
            for tid, kw, p, p_idx in tasks
        }

        for future in as_completed(futures):
            tid, kw, p = futures[future]
            try:
                future.result()
            except Exception as e:
                show_error(f"#{tid} {p} / {kw[:20]} 失败：{e}")

    console.print(f"\n[green][OK] 本次 baseline 日志已保存至：{log_path}[/green]")
    console.print(f"[dim]运行 python analyze.py {log_path} 查看统计[/dim]")


if __name__ == "__main__":
    platform_only = ""
    custom_count = 0
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--platform" and i + 1 < len(args):
            platform_only = args[i + 1].strip()
            i += 2
        elif args[i] == "--count" and i + 1 < len(args):
            try:
                custom_count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1
    run(platform_only=platform_only, custom_count=custom_count)
