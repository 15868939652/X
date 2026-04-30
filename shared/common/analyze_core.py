"""
读 logs/*.jsonl 出 baseline 报告。

用法:
    python analyze.py                      # 最新那份
    python analyze.py logs/xxx.jsonl       # 指定
    python analyze.py logs/*.jsonl         # 合并多份
"""

import glob
import json
import os
import sys
from collections import Counter, defaultdict
from statistics import mean, stdev


def load(paths):
    records = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def _m(xs):
    xs = [x for x in xs if x is not None]
    return round(mean(xs), 2) if xs else None


def _sd(xs):
    xs = [x for x in xs if x is not None]
    return round(stdev(xs), 2) if len(xs) >= 2 else None


def _group(records, key):
    g = defaultdict(list)
    for r in records:
        g[r.get(key, "?")].append(r)
    return g


def _title(s):
    print("\n" + "=" * 72)
    print(f"  {s}")
    print("=" * 72)


def overall(records):
    valid = [r for r in records if "final_score" in r]
    n = len(valid)
    _title(f"总体 ({n} 篇)")
    if not n:
        print("  无有效数据"); return
    first_pass = sum(1 for r in valid if r.get("retries", 0) == 0 and r.get("passed"))
    final_pass = sum(1 for r in valid if r.get("passed"))
    print(f"  首稿通过率               : {first_pass}/{n} = {first_pass/n*100:.1f}%")
    print(f"  最终通过率               : {final_pass}/{n} = {final_pass/n*100:.1f}%")
    print(f"  平均重试次数             : {_m([r.get('retries', 0) for r in valid])}")
    print(f"  重试分布                 : {dict(Counter(r.get('retries', 0) for r in valid))}")
    print(f"  初稿得分  均/标准差      : {_m([r.get('first_draft_score') for r in valid])} / {_sd([r.get('first_draft_score') for r in valid])}")
    print(f"  终稿得分  均/标准差      : {_m([r.get('final_score') for r in valid])} / {_sd([r.get('final_score') for r in valid])}")
    print(f"  初稿 LLM 分 / 规则分     : {_m([r.get('first_draft_llm_score') for r in valid])} / {_m([r.get('first_draft_rule_score') for r in valid])}")
    print(f"  终稿 LLM 分 / 规则分     : {_m([r.get('final_llm_score') for r in valid])} / {_m([r.get('final_rule_score') for r in valid])}")

    deltas = [r["final_score"] - r["first_draft_score"] for r in valid
              if r.get("first_draft_score") is not None and r.get("final_score") is not None]
    if deltas:
        print(f"  后处理平均增分            : {_m(deltas)}  (正值=后处理有效)")

    seg_used = sum(1 for r in valid if r.get("has_segments"))
    print(f"  分段生成成功率            : {seg_used}/{n} = {seg_used/n*100:.1f}%")


def per_group(records, key, label):
    _title(f"按 {label} 分组")
    groups = _group([r for r in records if "final_score" in r], key)
    hdr = f"  {label:<18} {'n':>4} {'首稿%':>7} {'最终%':>7} {'初稿':>6} {'终稿':>6} {'重试':>6}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for name, rs in sorted(groups.items(), key=lambda x: -len(x[1])):
        n = len(rs)
        fp = sum(1 for r in rs if r.get("retries", 0) == 0 and r.get("passed")) / n * 100
        pp = sum(1 for r in rs if r.get("passed")) / n * 100
        fs = _m([r.get("first_draft_score") for r in rs]) or 0
        fn = _m([r.get("final_score") for r in rs]) or 0
        rt = _m([r.get("retries", 0) for r in rs]) or 0
        print(f"  {str(name)[:18]:<18} {n:>4} {fp:>6.1f}% {pp:>6.1f}% {fs:>6} {fn:>6} {rt:>6}")


def tokens_and_cost(records):
    _title("LLM 调用与 Token 消耗")
    tier = defaultdict(lambda: {"prompt": 0, "completion": 0, "calls": 0})
    for r in records:
        for c in r.get("llm_calls", []) or []:
            t = c.get("tier", "?")
            tier[t]["calls"] += 1
            tier[t]["prompt"] += c.get("prompt_tokens") or 0
            tier[t]["completion"] += c.get("completion_tokens") or 0
    total_calls = sum(v["calls"] for v in tier.values())
    n = len([r for r in records if "final_score" in r]) or 1
    print(f"  总调用 : {total_calls}  (每篇 {total_calls/n:.2f} 次)")
    for t, v in sorted(tier.items()):
        print(f"  [{t}]  calls={v['calls']:>4}  prompt={v['prompt']:>8}  completion={v['completion']:>8}")


def problem_tags(records):
    _title("问题标签分布 (final_problems)")
    c = Counter()
    for r in records:
        for tag in r.get("final_problems", []) or []:
            c[tag] += 1
    if not c:
        print("  无问题标签（可能终稿全部通过或字段缺失）")
        return
    for tag, cnt in c.most_common():
        print(f"  {cnt:>4}  {tag}")


def rewrite_targets(records):
    _title("局部重写目标段分布")
    c = Counter()
    for r in records:
        for tgts in r.get("rewrite_targets", []) or []:
            for t in tgts:
                c[t] += 1
    if not c:
        print("  无重写记录（都是首稿通过或未触发重写）")
        return
    for t, cnt in c.most_common():
        print(f"  {cnt:>4}  {t}")


def main():
    if len(sys.argv) > 1:
        paths = []
        for arg in sys.argv[1:]:
            paths.extend(glob.glob(arg))
    else:
        paths = sorted(glob.glob(os.path.join("logs", "*.jsonl")))
        paths = paths[-1:] if paths else []

    if not paths:
        print("未找到日志文件。先跑一次 main.py 生成 logs/*.jsonl")
        sys.exit(1)

    print(f"读取 {len(paths)} 份日志:")
    for p in paths:
        print(f"  - {p}")

    records = load(paths)
    print(f"共 {len(records)} 条记录")

    overall(records)
    per_group(records, "platform", "平台")
    per_group(records, "mode", "模式")
    tokens_and_cost(records)
    problem_tags(records)
    rewrite_targets(records)


if __name__ == "__main__":
    main()
