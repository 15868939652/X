import unittest
from unittest import mock
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
PROJECT = ROOT / "projects" / "yiwu_weichuang"
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
if str(SHARED) not in sys.path:
    sys.path.append(str(SHARED))

import bootstrap_shared  # noqa: F401

from common import generator_core, llm as llm_module

FAKE_PROMPT_TEMPLATE = """{brand} 测试提示词模板。关键词：{关键词}。请生成一篇第一人称的文章。"""

FAKE_LLM_RESULT_RAW = """北京妇科医院检查经历分享

前段时间因为月经不调的问题，我拖了挺久，最后还是决定去北京这边一家妇科专科医院看看。

说实话去医院之前心里还是有点紧张的，毕竟平时也不太关注这方面的信息。我是先在手机上挂了个号，到院之后感觉流程比我想的要简单一些。

医生问得还算细，除了问症状还问了平时作息和饮食情况。先做了个基础检查，过程没有我想得那么复杂。医生看完结果之后解释得比较清楚，把需要注意的地方都讲了一下。

开的药不算多，主要还是按常规处理。医生也说如果后面情况反复再考虑进一步检查，不用一次全做完。

看完之后心里踏实了不少，至少把我当时最担心的情况排掉了。这次经历让我觉得，有问题还是早点去看看比较好，比一直拖着瞎想要强。

这些只是我个人的经历，每个人的情况不一样，仅供参考。"""

FAKE_LLM_RESULT_SEGMENTED = """北京妇科医院检查经历分享

【开头】前段时间因为月经不调的问题，我拖了挺久，最后还是决定去北京这边一家妇科专科医院看看。说实话去医院之前心里还是有点紧张的。

【中间】医生问得还算细，除了问症状还问了平时作息和饮食情况。先做了个基础检查，过程没有我想得那么复杂。医生看完结果之后解释得比较清楚，把需要注意的地方都讲了一下。

【结尾】看完之后心里踏实了不少，至少把我当时最担心的点排掉了。这些只是我个人的经历，仅供参考。"""


def _fake_llm_ok(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
    return {
        "provider": "fake",
        "model": "fake-model",
        "tier": "fake:pro",
        "content": FAKE_LLM_RESULT_SEGMENTED,
        "prompt_tokens": 200,
        "completion_tokens": 300,
    }


def _fake_llm_one_shot(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
    return {
        "provider": "fake",
        "model": "fake-model",
        "tier": "fake:pro",
        "content": FAKE_LLM_RESULT_RAW,
        "prompt_tokens": 150,
        "completion_tokens": 250,
    }


def _fake_rule_score_pass(article: str, platform: str = "", mode: str = "") -> dict:
    return {
        "score": 85,
        "problems": [],
        "reason": "符合要求",
        "length": len(article),
        "repetition": 0.05,
    }


def _fake_detailed_score_pass(article: str, platform: str = "sohu", mode: str = "info") -> dict:
    return {
        "score": 80,
        "problems": [],
        "reason": "通过",
        "llm": {"score": 75, "problems": [], "reason": "ok"},
        "rule": {"score": 85, "problems": [], "reason": "ok", "length": len(article), "repetition": 0.05},
    }


def _fake_profile() -> dict:
    return {
        "key": "yiwu_weichuang",
        "brand": "测试医院",
        "generator_settings": {},
    }


def _start_patches():
    patches = [
        mock.patch("common.generator_core._load", return_value=FAKE_PROMPT_TEMPLATE),
        mock.patch("common.generator_core._load_examples", return_value=""),
        mock.patch("common.generator_core.get_active_profile", return_value=_fake_profile()),
        mock.patch("common.generator_core.random_profile", return_value="普通用户视角"),
        mock.patch("common.generator_core.random_style", return_value="口语化表达"),
        mock.patch("common.generator_core.random_trigger", return_value="朋友推荐去看看"),
        mock.patch("common.generator_core.random.choices", return_value=["info"]),
        mock.patch("common.generator_core._layer_dynamics", return_value={
            "info_density": "中", "hesitation": "中", "detail_level": "中", "sentence_pattern": "短句为主",
        }),
        mock.patch("common.generator_core.step"),
        mock.patch("common.generator_core.show_params"),
        mock.patch("common.generator_core.show_done"),
        mock.patch("common.generator_core.show_score"),
        mock.patch("common.generator_core.show_retry"),
    ]
    for p in patches:
        p.start()
    return patches


def _stop_patches(patches):
    for p in patches:
        p.stop()


PROVIDER_KEYS_FIXTURE = {"fake": "sk-test", "fail": "sk-test", "primary": "sk-p", "fallback": "sk-f"}


class PipelineFastModeTests(unittest.TestCase):
    def test_fast_mode_produces_article_and_record(self) -> None:
        with mock.patch.dict(llm_module._PROVIDER_HANDLERS, {"fake": _fake_llm_ok}, clear=False):
            with mock.patch.dict(llm_module._PROVIDER_KEYS, PROVIDER_KEYS_FIXTURE, clear=False):
                with mock.patch("common.generator_core.rule_score", return_value=_fake_rule_score_pass(FAKE_LLM_RESULT_SEGMENTED)):
                    patches = _start_patches()
                    try:
                        title, article, record = generator_core.generate_article(
                            "月经不调", "sohu", "搜狐平台", generator_provider="fake", generation_mode="fast",
                        )
                    finally:
                        _stop_patches(patches)

        self.assertIsInstance(title, str)
        self.assertGreater(len(title), 0)
        self.assertIsInstance(article, str)
        self.assertGreater(len(article), 50)
        self.assertEqual(record["generation_mode"], "fast")
        self.assertEqual(record["retries"], 0)
        self.assertIn("final_score", record)
        self.assertIn("quality_steps_skipped", record)

    def test_fast_mode_records_stages(self) -> None:
        with mock.patch.dict(llm_module._PROVIDER_HANDLERS, {"fake": _fake_llm_ok}, clear=False):
            with mock.patch.dict(llm_module._PROVIDER_KEYS, PROVIDER_KEYS_FIXTURE, clear=False):
                with mock.patch("common.generator_core.rule_score", return_value=_fake_rule_score_pass(FAKE_LLM_RESULT_SEGMENTED)):
                    patches = _start_patches()
                    try:
                        _, _, record = generator_core.generate_article(
                            "月经不调", "sohu", "搜狐平台", generator_provider="fake", generation_mode="fast",
                        )
                    finally:
                        _stop_patches(patches)

        self.assertIn("stages", record)
        stages = record["stages"]
        self.assertIn("prompt_build", stages)
        self.assertIn("draft_generation", stages)
        self.assertIn("total", stages)
        for name in ("prompt_build", "draft_generation", "total"):
            self.assertIn("elapsed_ms", stages[name])
            self.assertGreater(stages[name]["elapsed_ms"], -1)


class PipelineQualityModeTests(unittest.TestCase):
    def test_quality_mode_calls_detailed_scorer(self) -> None:
        with mock.patch.dict(llm_module._PROVIDER_HANDLERS, {"fake": _fake_llm_ok}, clear=False):
            with mock.patch.dict(llm_module._PROVIDER_KEYS, PROVIDER_KEYS_FIXTURE, clear=False):
                with mock.patch("common.generator_core.score_article_detailed", return_value=_fake_detailed_score_pass(FAKE_LLM_RESULT_SEGMENTED)):
                    patches = _start_patches()
                    try:
                        _, _, record = generator_core.generate_article(
                            "月经不调", "sohu", "搜狐平台", generator_provider="fake", generation_mode="quality",
                        )
                    finally:
                        _stop_patches(patches)

        self.assertEqual(record["generation_mode"], "quality")
        self.assertIn("final_score", record)

    def test_quality_mode_retries_on_low_score(self) -> None:
        with mock.patch.dict(llm_module._PROVIDER_HANDLERS, {"fake": _fake_llm_ok}, clear=False):
            with mock.patch.dict(llm_module._PROVIDER_KEYS, PROVIDER_KEYS_FIXTURE, clear=False):
                with mock.patch("common.generator_core.score_article_detailed", return_value={
                    "score": 55, "problems": ["length_too_short"], "reason": "字数不足",
                    "llm": {"score": 50, "problems": ["length_too_short"], "reason": "短"},
                    "rule": {"score": 60, "problems": ["length_too_short"], "reason": "短", "length": 200, "repetition": 0.1},
                }):
                    with mock.patch("common.generator_core.rule_score", return_value=_fake_rule_score_pass(FAKE_LLM_RESULT_SEGMENTED)):
                        with mock.patch("common.generator_core.apply_random_rewrite", return_value=FAKE_LLM_RESULT_SEGMENTED):
                            patches = _start_patches()
                            try:
                                _, _, record = generator_core.generate_article(
                                    "月经不调", "sohu", "搜狐平台", generator_provider="fake", generation_mode="quality",
                                )
                            finally:
                                _stop_patches(patches)

        self.assertEqual(record["retries"], 1)
        self.assertIn("retry_scores", record)


class PipelineOneShotTests(unittest.TestCase):
    def test_one_shot_mode_produces_article(self) -> None:
        with mock.patch.dict(llm_module._PROVIDER_HANDLERS, {"fake": _fake_llm_one_shot}, clear=False):
            with mock.patch.dict(llm_module._PROVIDER_KEYS, PROVIDER_KEYS_FIXTURE, clear=False):
                patches = _start_patches()
                try:
                    title, article, record = generator_core.generate_article(
                        "月经不调", "sohu", "搜狐平台", generator_provider="fake", generation_mode="one_shot",
                    )
                finally:
                    _stop_patches(patches)

        self.assertEqual(record["generation_mode"], "one_shot")
        self.assertIsInstance(title, str)
        self.assertGreater(len(title), 0)
        self.assertIsInstance(article, str)
        self.assertGreater(len(article), 50)


class PipelineFallbackTests(unittest.TestCase):
    def test_draft_generation_falls_back_on_failure(self) -> None:
        calls = {"count": 0}

        def flaky_handler(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
            calls["count"] += 1
            if calls["count"] <= 2:
                raise RuntimeError("primary fails")
            return _fake_llm_ok(prompt)

        with mock.patch.dict(llm_module._PROVIDER_HANDLERS, {"primary": flaky_handler, "fallback": _fake_llm_ok}, clear=False):
            with mock.patch.dict(llm_module._PROVIDER_KEYS, PROVIDER_KEYS_FIXTURE, clear=False):
                with mock.patch("common.generator_core.rule_score", return_value=_fake_rule_score_pass(FAKE_LLM_RESULT_SEGMENTED)):
                    patches = _start_patches()
                    try:
                        _, _, record = generator_core.generate_article(
                            "月经不调", "sohu", "搜狐平台", generator_provider="primary", fallback_provider="fallback", generation_mode="fast",
                        )
                    finally:
                        _stop_patches(patches)

        self.assertTrue(record["fallback_used"])

    def test_draft_generation_raises_on_all_failures(self) -> None:
        def always_fail(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
            raise RuntimeError("always fails")

        with mock.patch.dict(llm_module._PROVIDER_HANDLERS, {"fail": always_fail}, clear=False):
            with mock.patch.dict(llm_module._PROVIDER_KEYS, PROVIDER_KEYS_FIXTURE, clear=False):
                patches = _start_patches()
                try:
                    generator_core.generate_article(
                        "月经不调", "sohu", "搜狐平台", generator_provider="fail", generation_mode="fast",
                    )
                    self.fail("Expected GenerationTaskError")
                except generator_core.GenerationTaskError as exc:
                    self.assertEqual(exc.partial_record["failed_stage"], "draft_generation")
                finally:
                    _stop_patches(patches)


if __name__ == "__main__":
    unittest.main()
