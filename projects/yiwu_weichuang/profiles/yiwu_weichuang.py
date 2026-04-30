PROFILE = {
    "key": "yiwu_weichuang",
    "brand": "义乌微创医院",
    "city": "义乌",
    "hospital_type": "专科医院",
    "departments": {
        "妇科": 0.80,
        "男科": 0.10,
        "常规体检": 0.10,
    },
    "department_keywords": {
        "妇科": ["妇科", "白带", "月经", "人流", "备孕", "宫颈", "妇科检查", "早孕", "产后", "不孕", "不育"],
        "男科": ["男科", "前列腺", "男性", "包皮", "龟头", "早泄", "阳痿", "勃起"],
    },
    "keyword_file": "data/keywords/yiwu_weichuang.xlsx",
    "brand_aliases": ["义乌微创医院"],
    "generator_settings": {
        "title_rule_variant": "yiwu_weichuang",
        "normalize_foreign_brands": True,
        "filter_foreign_examples": True,
    },
    "platform_rules": {
        "sohu": {
            "title_style": "descriptive",
            "must_mention_brand_in_title": True,
            "brand_need_not_be_prefix": True,
            "forbid_question": True,
            "forbid_judgment": True,
            "forbid_specific_department": True,
            "forbid_specific_disease": True,
        }
    },
    "content_rules": {
        "comparison_terms": ["综合性医院", "专科医院"],
        "default_tone": "中立偏正向",
    },
}
