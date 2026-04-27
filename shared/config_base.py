# ========================= 共享基础配置 =========================
# 所有子项目共用的 API 密钥、模型名称、生成参数
# 每个项目的 config.py 只需定义 ACTIVE_PROFILE 和 BRAND 后 import *

# --- 模型选择 ---
GENERATOR_PROVIDER = "doubao"
AUX_PROVIDER = "doubao"
MODEL_TYPE = GENERATOR_PROVIDER

# --- 豆包（火山引擎）---
DOUBAO_API_KEY    = "e4911c31-ef61-4d68-bf9e-07d430466a16"
DOUBAO_BASE_URL   = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_MAIN_MODEL = "doubao-seed-2-0-pro-260215"
DOUBAO_FAST_MODEL = "doubao-seed-2-0-lite-260215"

# --- GPT（OpenAI）---
OPENAI_API_KEY    = ""
OPENAI_MAIN_MODEL = "gpt-4o"
OPENAI_FAST_MODEL = ""

# --- Packy API（备用）---
PACKY_API_KEY     = "sk-L3ZWO7B2Gt1qAwzCNKAXMQQ86cdoanb9KQynrlqIxmH35OoS"
PACKY_BASE_URL    = "https://www.packyapi.com/v1"
PACKY_MAIN_MODEL  = "gpt-5.4"
PACKY_FAST_MODEL  = ""

# --- 生成控制 ---
OUTPUT_PER_KEYWORD = 1
MIN_SCORE          = 70
MAX_RETRY          = 2
CONCURRENT_WORKERS = 3
BATCH_SIZE         = 12
SCORER_USE_PRO     = False

PLATFORM_MIN_SCORE = {
    "toutiao": 70,
    "zhihu": 70,
    "sohu": 70,
    "baijiahao": 70,
}
