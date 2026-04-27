from config import ACTIVE_PROFILE
from profiles import PROFILES


def get_active_profile() -> dict:
    profile = PROFILES.get(ACTIVE_PROFILE)
    if not profile:
        raise ValueError(f"未知 ACTIVE_PROFILE: {ACTIVE_PROFILE}")
    return profile
