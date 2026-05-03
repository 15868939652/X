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

from common import llm, scorer


class LLMRetryTests(unittest.TestCase):
    def test_call_llm_result_retries_until_success(self) -> None:
        calls = {"count": 0}

        def flaky_handler(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
            calls["count"] += 1
            if calls["count"] < 3:
                raise RuntimeError("temporary 500")
            return {
                "provider": "fake",
                "model": "fake-model",
                "tier": "fake:pro",
                "content": "ok",
                "prompt_tokens": 11,
                "completion_tokens": 22,
            }

        with mock.patch.dict(llm._PROVIDER_HANDLERS, {"fake": flaky_handler}, clear=False):
            with mock.patch.dict(llm._PROVIDER_KEYS, {"fake": "valid-looking-key"}, clear=False):
                with mock.patch("common.llm.time.sleep") as mocked_sleep:
                    result = llm.call_llm_result("hello", provider="fake", retries=3)

        self.assertTrue(result.ok)
        self.assertEqual(result.content, "ok")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(calls["count"], 3)
        self.assertEqual(mocked_sleep.call_count, 2)

    def test_call_llm_result_marks_continuous_failures(self) -> None:
        def failing_handler(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
            raise TimeoutError("timeout")

        with mock.patch.dict(llm._PROVIDER_HANDLERS, {"fake_fail": failing_handler}, clear=False):
            with mock.patch.dict(llm._PROVIDER_KEYS, {"fake_fail": "valid-looking-key"}, clear=False):
                with mock.patch("common.llm.time.sleep"):
                    result = llm.call_llm_result("hello", provider="fake_fail", retries=2)

        self.assertTrue(result.failed)
        self.assertEqual(result.attempts, 3)
        self.assertIn("timeout", result.error)

    def test_call_llm_result_stops_retrying_on_auth_error(self) -> None:
        calls = {"count": 0}

        def auth_fail_handler(prompt: str, fast: bool = False, main_model: str = None, fast_model: str = None) -> dict:
            calls["count"] += 1
            raise RuntimeError("401 Unauthorized")

        with mock.patch.dict(llm._PROVIDER_HANDLERS, {"fake_auth": auth_fail_handler}, clear=False):
            with mock.patch.dict(llm._PROVIDER_KEYS, {"fake_auth": "valid-looking-key"}, clear=False):
                with mock.patch("common.llm.time.sleep") as mocked_sleep:
                    result = llm.call_llm_result("hello", provider="fake_auth", retries=3)

        self.assertTrue(result.failed)
        self.assertEqual(result.attempts, 1)
        self.assertIn("401", result.error)
        self.assertEqual(calls["count"], 1)
        self.assertEqual(mocked_sleep.call_count, 0)


class ScorerParsingTests(unittest.TestCase):
    def test_parse_json_payload(self) -> None:
        parsed = scorer._parse_llm('{"score": 85, "problems": ["summary"], "reason": "结尾总结痕迹明显"}')
        self.assertEqual(parsed["score"], 85)
        self.assertEqual(parsed["problems"], ["summary"])
        self.assertEqual(parsed["format"], "json")

    def test_parse_legacy_payload_with_warning(self) -> None:
        parsed = scorer._parse_llm("得分：80\n问题标签：summary,paired_structure\n扣分说明：结尾太像总结")
        self.assertEqual(parsed["score"], 80)
        self.assertEqual(parsed["format"], "legacy")
        self.assertIn("warning", parsed)

    def test_invalid_payload_becomes_scorer_error(self) -> None:
        parsed = scorer._parse_llm("not-json and not-legacy")
        self.assertEqual(parsed["score"], -1)
        self.assertIn(scorer.SCORER_ERROR_TAG, parsed["problems"])
        self.assertEqual(parsed["status"], "error")


class ScoreFusionTests(unittest.TestCase):
    def test_weighted_blend_above_50(self) -> None:
        fake_llm = {"score": 80, "problems": ["summary"], "reason": "结尾总结", "attempts": 1, "provider": "fake", "model": "fake"}
        fake_rule = {"score": 90, "problems": ["length_too_long"], "reason": "字数超限", "length": 600, "repetition": 0.1}
        with mock.patch("common.scorer.score_llm", return_value=fake_llm):
            with mock.patch("common.scorer.rule_score", return_value=fake_rule):
                result = scorer.score_article_detailed("test article", platform="sohu", mode="info")
        self.assertEqual(result["score"], round(80 * 0.5 + 90 * 0.5))

    def test_llm_score_below_50_dominates(self) -> None:
        fake_llm = {"score": 40, "problems": ["ai_taste"], "reason": "AI味重", "attempts": 1, "provider": "fake", "model": "fake"}
        fake_rule = {"score": 90, "problems": [], "reason": "无规则扣分项", "length": 500, "repetition": 0.05}
        with mock.patch("common.scorer.score_llm", return_value=fake_llm):
            with mock.patch("common.scorer.rule_score", return_value=fake_rule):
                result = scorer.score_article_detailed("test article", platform="sohu", mode="info")
        self.assertEqual(result["score"], 40)

    def test_llm_error_propagates(self) -> None:
        fake_llm = {"score": -1, "problems": ["scorer_error"], "reason": "评分失败", "attempts": 1, "provider": "fake", "model": "fake", "format": "error", "status": "error"}
        fake_rule = {"score": 90, "problems": [], "reason": "无规则扣分项", "length": 500, "repetition": 0.05}
        with mock.patch("common.scorer.score_llm", return_value=fake_llm):
            with mock.patch("common.scorer.rule_score", return_value=fake_rule):
                result = scorer.score_article_detailed("test article")
        self.assertEqual(result["score"], -1)


class ConfigValidationTests(unittest.TestCase):
    def test_provider_key_empty_string_detected(self) -> None:
        with mock.patch.dict(llm._PROVIDER_KEYS, {"empty_provider": ""}, clear=False):
            error = llm._provider_key_missing("empty_provider")
            self.assertTrue(error)

    def test_provider_key_valid_detected(self) -> None:
        with mock.patch.dict(llm._PROVIDER_KEYS, {"valid_provider": "sk-abc123"}, clear=False):
            error = llm._provider_key_missing("valid_provider")
            self.assertFalse(error)

    def test_provider_not_in_keys_detected(self) -> None:
        with mock.patch.dict(llm._PROVIDER_KEYS, {}, clear=True):
            error = llm._provider_key_missing("unknown_provider")
            self.assertTrue(error)


if __name__ == "__main__":
    unittest.main()
