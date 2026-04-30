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

SCRIPT = r"""
import hashlib
import importlib
import json

import bootstrap_shared  # noqa: F401
from common import legacy_prompt_builder as legacy
legacy_build_prompt = legacy._build_prompt
new = importlib.import_module('common.generator_core')

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
        old_prompt, old_segmented = legacy_build_prompt(**kwargs)
        new_prompt, new_segmented = new._build_prompt(**kwargs)
        cases.append({
            'platform': platform,
            'mode': mode,
            'old_hash': hashlib.sha256(old_prompt.encode('utf-8')).hexdigest(),
            'new_hash': hashlib.sha256(new_prompt.encode('utf-8')).hexdigest(),
            'prompt_equal': old_prompt == new_prompt,
            'segmented_equal': old_segmented == new_segmented,
        })
print(json.dumps(cases, ensure_ascii=True))
"""


class PromptIdentityTests(unittest.TestCase):
    def test_prompt_identity_across_projects(self) -> None:
        for project_dir in PROJECTS:
            result = subprocess.run(
                [sys.executable, '-c', SCRIPT],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            cases = json.loads(result.stdout)
            failures = [
                case for case in cases
                if not case['prompt_equal'] or not case['segmented_equal']
            ]
            self.assertFalse(
                failures,
                msg=f'{project_dir.name} prompt drift detected: {json.dumps(failures, ensure_ascii=False)}',
            )


if __name__ == '__main__':
    unittest.main()
