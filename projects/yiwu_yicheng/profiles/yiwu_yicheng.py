PROFILE = {
    "key": "yiwu_yicheng",
    "brand": "义乌义城医院",
    "city": "义乌",
    "hospital_type": "专科医院",
    "departments": {
        "妇科": 0.30,
        "皮肤科": 0.60,
        "常规体检": 0.10,
    },
    "department_keywords": {
        "妇科": ["妇科", "白带", "月经", "人流", "备孕", "宫颈", "妇科检查"],
        "皮肤科": ["皮肤", "痘痘", "皮炎", "湿疹", "痤疮", "毛囊炎", "激光", "光子"],
    },
    "keyword_file": "data/keywords/yiwu_yicheng.xlsx",
    "brand_aliases": ["义乌义城医院"],
    "generator_settings": {
        "title_rule_variant": "yiwu_yicheng",
        "normalize_foreign_brands": False,
        "filter_foreign_examples": False,
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
