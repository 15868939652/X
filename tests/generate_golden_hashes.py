"""Generate golden prompt hash snapshots for prompt identity tests.

Usage:
    cd projects/yiwu_weichuang && python ../../tests/generate_golden_hashes.py
    cd projects/yiwu_yicheng && python ../../tests/generate_golden_hashes.py
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.append("../../shared")
import bootstrap_shared  # noqa: F401
from common import generator_core as gen

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURES.mkdir(exist_ok=True)

cases = []
platform_prompts = {
    "sohu": "PLATFORM_PROMPT_SOHU",
    "baijiahao": "PLATFORM_PROMPT_BJH",
    "toutiao": "PLATFORM_PROMPT_TOUTIAO",
}
for platform, platform_prompt in platform_prompts.items():
    for mode in ["info", "light_exp", "other_exp", "exp"]:
        dynamics = {
            "info_density": "MEDIUM",
            "hesitation": "LOW",
            "detail_level": "HIGH",
            "sentence_pattern": "MIXED",
        }
        kwargs = {
            "keyword": "KEYWORD_SAMPLE",
            "mode": mode,
            "profile": "PROFILE_SAMPLE",
            "style": "STYLE_SAMPLE",
            "trigger": "TRIGGER_SAMPLE",
            "platform": platform,
            "platform_prompt": platform_prompt,
            "dynamics": dynamics,
        }
        prompt, segmented = gen._build_prompt(**kwargs)
        cases.append({
            "platform": platform,
            "mode": mode,
            "hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "segmented": segmented,
        })

cwd = Path.cwd()
project_name = cwd.name
output = FIXTURES / f"prompt_snapshots_{project_name}.json"
output.write_text(json.dumps(cases, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(cases)} snapshots to {output}")
