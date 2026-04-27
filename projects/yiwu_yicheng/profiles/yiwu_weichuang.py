PROFILE = {
    "key": "yiwu_weichuang",
    "brand": "义乌微创医院",
    "city": "义乌",
    "hospital_type": "专科医院",
    "departments": {
        "妇科": 0.90,
        "男科": 0.10,
    },
    "keyword_file": "data/keywords/yiwu_weichuang.xlsx",
    "brand_aliases": ["义乌微创医院"],
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
