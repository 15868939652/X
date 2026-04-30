# ========================= 共享基础配置 =========================
# 当前版本回滚为“代码内置配置”模式，打包后的 EXE 不再依赖 .env 或系统环境变量。

# --- 模型选择 ---
GENERATOR_PROVIDER = "doubao"
AUX_PROVIDER = "doubao"
MODEL_TYPE = GENERATOR_PROVIDER

# --- 闃舵妯″瀷璺敱 ---
# 鍙€夊€硷細doubao / qwen / glm / openai / packy
# 快速模式仍使用原豆包链路；下面的阶段路由主要用于 quality 模式。
KEYWORD_PROVIDER = "doubao"
DRAFT_PROVIDER = "doubao"
SCORE_PROVIDER = "deepseek"
ANTI_AI_PROVIDER = "doubao"
REWRITE_PROVIDER = "qwen"

# --- 豆包（火山引擎）---
DOUBAO_API_KEY = "e4911c31-ef61-4d68-bf9e-07d430466a16"
DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_MAIN_MODEL = "doubao-seed-2-0-pro-260215"
DOUBAO_FAST_MODEL = "doubao-seed-2-0-lite-260215"

# --- Qwen锛堥€氫箟鍗冮棶 OpenAI compatible锛?---
QWEN_API_KEY = "sk-3a77256a152f4bd7bc6f64ccdd8dad01"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_MAIN_MODEL = "qwen3.6-plus"
QWEN_FAST_MODEL = "qwen3.6"

# --- GLM锛堟櫤璋?OpenAI compatible锛?---
GLM_API_KEY = "df712fe9fa9b468f9e92caa0708e17b4.6S60KkrrgVvj016P"
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
GLM_MAIN_MODEL = "glm-5.1"
GLM_FAST_MODEL = "glm-5.1"

# --- DeepSeek OpenAI compatible ---
DEEPSEEK_API_KEY = "sk-c6ebafb8b19845b08643f5b564e3e702"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MAIN_MODEL = "deepseek-v4-flash"
DEEPSEEK_FAST_MODEL = "deepseek-v4-flash"

# --- OpenAI（可选）---
OPENAI_API_KEY = ""
OPENAI_MAIN_MODEL = "gpt-4o"
OPENAI_FAST_MODEL = ""

# --- Packy API（备用）---
PACKY_API_KEY = ""
PACKY_BASE_URL = "https://www.packyapi.com/v1"
PACKY_MAIN_MODEL = "gpt-5.4"
PACKY_FAST_MODEL = ""

# --- 生成控制 ---
OUTPUT_PER_KEYWORD = 1
MIN_SCORE = 70
MAX_RETRY = 2
CONCURRENT_WORKERS = 3
BATCH_SIZE = 12
SCORER_USE_PRO = False
LLM_MAX_CONCURRENT = 2  # 全局并发 LLM 调用上限（避免 API 过载超时）

PLATFORM_MIN_SCORE = {
    "toutiao": 70,
    "zhihu": 70,
    "sohu": 70,
    "baijiahao": 70,
}
