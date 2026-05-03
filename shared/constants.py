"""Centralized constants shared across all modules.

Import this module to reference scoring weights, mode definitions,
and other magic numbers that were previously scattered across
generator_core, scorer, and config_base.
"""

# --- 评分权重 (scoring weights) ---
W_LLM = 0.5
W_RULE = 0.5
SCORER_ERROR_TAG = "scorer_error"

# --- 生成控制默认值 ---
DEFAULT_MIN_SCORE = 70
DEFAULT_MAX_RETRY = 2
DEFAULT_CONCURRENT_WORKERS = 3
DEFAULT_BATCH_SIZE = 12
DEFAULT_LLM_MAX_CONCURRENT = 2

# --- 平台最低分默认值 ---
DEFAULT_PLATFORM_MIN_SCORE = {
    "toutiao": 70,
    "zhihu": 70,
    "sohu": 70,
    "baijiahao": 70,
}

# --- 写作模式定义 (mode → (prompt_file, selection_weight)) ---
MODES = {
    "info": ("prompts/article_base.txt", 0.30),
    "light_exp": ("prompts/article_base.txt", 0.24),
    "other_exp": ("prompts/article_base.txt", 0.14),
    "exp": ("prompts/article_exp.txt", 0.32),
}
MODE_NAMES = list(MODES.keys())
MODE_WEIGHTS = [item[1] for item in MODES.values()]
SEGMENTED_MODES = {"info", "light_exp", "other_exp", "exp"}

# --- 规则评分器常量 ---
# 按写作模式的字数要求
MODE_LENGTH = {
    "info":       (400, 900),
    "light_exp":  (400, 900),
    "other_exp":  (400, 900),
    "exp":        (200, 500),
    "hesitate":   (150, 350),
    "short":      (100, 250),
}

# 平台字数要求 (fallback)
PLATFORM_LENGTH = {
    "toutiao":   (200, 800),
    "zhihu":     (300, 900),
    "sohu":      (400, 1500),
    "baijiahao": (300, 1200),
}
