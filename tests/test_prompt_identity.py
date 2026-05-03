"""Prompt identity test — compares generator_core._build_prompt output against golden snapshots.

To regenerate golden files after an intentional prompt change:
    cd projects/yiwu_weichuang && python ../../tests/generate_golden_hashes.py
    cd projects/yiwu_yicheng && python ../../tests/generate_golden_hashes.py
"""
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = [
    ROOT / "projects" / "yiwu_weichuang",
    ROOT / "projects" / "yiwu_yicheng",
]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

SCRIPT = r"""
import hashlib
import json
import sys
from pathlib import Path

import bootstrap_shared  # noqa: F401
from common import generator_core as gen

cases = []
platform_prompts = {
    'sohu': 'PLATFORM_PROMPT_SOHU',
    'baijiahao': 'PLATFORM_PROMPT_BJH',
    'toutiao': 'PLATFORM_PROMPT_TOUTIAO',
}
for platform, platform_prompt in platform_prompts.items():
    for mode in ['info', 'light_exp', 'other_exp', 'exp']:
        dynamics = {
            'info_density': 'MEDIUM',
            'hesitation': 'LOW',
            'detail_level': 'HIGH',
            'sentence_pattern': 'MIXED',
        }
        kwargs = {
            'keyword': 'KEYWORD_SAMPLE',
            'mode': mode,
            'profile': 'PROFILE_SAMPLE',
            'style': 'STYLE_SAMPLE',
            'trigger': 'TRIGGER_SAMPLE',
            'platform': platform,
            'platform_prompt': platform_prompt,
            'dynamics': dynamics,
        }
        prompt, segmented = gen._build_prompt(**kwargs)
        cases.append({
            'platform': platform,
            'mode': mode,
            'hash': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
            'segmented': segmented,
        })
print(json.dumps(cases, ensure_ascii=True))
"""


class PromptIdentityTests(unittest.TestCase):
    def test_prompt_identity_across_projects(self) -> None:
        for project_dir in PROJECTS:
            golden_file = FIXTURES / f"prompt_snapshots_{project_dir.name}.json"
            with open(golden_file, "r", encoding="utf-8") as f:
                golden = json.load(f)

            result = subprocess.run(
                [sys.executable, "-c", SCRIPT],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            current = json.loads(result.stdout)
            failures = []
            for case in current:
                expected = next(
                    (g for g in golden if g["platform"] == case["platform"] and g["mode"] == case["mode"]),
                    None,
                )
                if expected is None:
                    failures.append(f"{case['platform']}/{case['mode']}: missing from golden file")
                elif case["hash"] != expected["hash"]:
                    failures.append(
                        f"{case['platform']}/{case['mode']}: hash mismatch\n"
                        f"  expected: {expected['hash']}\n"
                        f"  got:      {case['hash']}"
                    )
            self.assertFalse(
                failures,
                msg=f"{project_dir.name} prompt drift detected:\n" + "\n".join(failures),
            )

    def test_segmented_flags_match(self) -> None:
        for project_dir in PROJECTS:
            result = subprocess.run(
                [sys.executable, "-c", SCRIPT],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            current = json.loads(result.stdout)
            for case in current:
                expected_seg = case["mode"] in {"info", "light_exp", "other_exp", "exp"}
                self.assertEqual(
                    case["segmented"],
                    expected_seg,
                    msg=f"{project_dir.name} {case['platform']}/{case['mode']}: segmented={case['segmented']}, expected={expected_seg}",
                )


if __name__ == "__main__":
    unittest.main()
