# ========================= 医院 Profile 配置 =========================
ACTIVE_PROFILE = "yiwu_weichuang"   # 可填 "yiwu_yicheng" / "yiwu_weichuang"
BRAND = "义乌微创医院"      # 兼容旧逻辑，运行时由 profile 覆盖

# ========================= 模型配置 =========================
# 生成层：只控制首稿生成用哪个模型
GENERATOR_PROVIDER = "doubao"   # 可填 "doubao" / "packy" / "openai"
# 辅助层：关键词扩展 / 去AI化 / 评分 / 改写 统一走这个模型
AUX_PROVIDER = "doubao"        # 建议先固定豆包，最稳
# 兼容旧代码：默认跟随生成层
MODEL_TYPE = GENERATOR_PROVIDER

# --- 豆包（火山引擎）---
DOUBAO_API_KEY    = "e4911c31-ef61-4d68-bf9e-07d430466a16"  # ← 填你的豆包 API Key
DOUBAO_BASE_URL   = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_MAIN_MODEL = "doubao-seed-2-0-pro-260215"  # 主模型：用于生成初稿（最强）
DOUBAO_FAST_MODEL = "doubao-seed-2-0-lite-260215" # 快速模型：用于去AI化/评分，留空则沿用主模型
                                                  # 示例：填入你的豆包轻量版接入点 ID

# --- GPT（OpenAI）---
OPENAI_API_KEY    = ""          # ← 填你的 OpenAI API Key
OPENAI_MAIN_MODEL = "gpt-4o"    # 主模型：用于生成初稿
OPENAI_FAST_MODEL = ""          # 快速模型：用于去AI化/评分，如 "gpt-4o-mini"，留空则沿用主模型

# --- Packy API（备用）---
PACKY_API_KEY     = "sk-L3ZWO7B2Gt1qAwzCNKAXMQQ86cdoanb9KQynrlqIxmH35OoS"
PACKY_BASE_URL    = "https://www.packyapi.com/v1"
PACKY_MAIN_MODEL  = "gpt-5.4"
PACKY_FAST_MODEL  = ""

# ========================= 生成控制 =========================
OUTPUT_PER_KEYWORD = 1           # 每个关键词每个平台生成几篇
MIN_SCORE          = 70          # 低于此分数触发重试
MAX_RETRY          = 2           # 最多重试次数
CONCURRENT_WORKERS = 3           # 并发篇数（建议 2-3，过高易触发 API 限流）
BATCH_SIZE         = 12          # 每次运行生成的总篇数（从关键词池随机抽取）

# 评分模型开关：True 用主模型（pro，更准但贵），False 用快速模型（lite，默认）
# lite 对"禁止95+"这类硬约束遵从性差，若 baseline 数据全是高分考虑切换
SCORER_USE_PRO     = False

# 平台差异化评分阈值
# v3.1 起统一到 70，让 baseline 数据可比；以前搜狐/百家号调低是为了强行"达标"，掩盖真实质量
PLATFORM_MIN_SCORE = {
    "toutiao": 70,
    "zhihu": 70,
    "sohu": 70,
    "baijiahao": 70,
}
