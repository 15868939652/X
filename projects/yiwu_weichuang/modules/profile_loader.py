from config import ACTIVE_PROFILE
from profiles import PROFILES


def get_active_profile() -> dict:
    profile = PROFILES.get(ACTIVE_PROFILE)
    if not profile:
        raise ValueError(f"Unknown ACTIVE_PROFILE: {ACTIVE_PROFILE}")
    return profile


def get_other_profiles() -> list[dict]:
    return [
        profile
        for key, profile in PROFILES.items()
        if key != ACTIVE_PROFILE
    ]


def get_other_brand_aliases() -> list[str]:
    aliases: list[str] = []
    for profile in get_other_profiles():
        brand = str(profile.get("brand", "")).strip()
        if brand:
            aliases.append(brand)
        for alias in profile.get("brand_aliases", []):
            alias = str(alias).strip()
            if alias:
                aliases.append(alias)
    return list(dict.fromkeys(aliases))
