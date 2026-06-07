"""
Capability Registry — Agent 类型定义
"""

CAPABILITY_REGISTRY = {
    "workshop": {
        "name": "配药师",
        "capabilities": ["recommend_product", "build_routine", "check_conflicts"],
        "required_model": "pro",
        "interruptible": True,
        "timeout_s": 30,
        "priority": 10,
    },
    "diagnosis": {
        "name": "问卷师",
        "capabilities": ["skin_diagnosis", "collect_profile"],
        "required_model": "flash",
        "interruptible": False,
        "timeout_s": 600,
        "priority": 5,
    },
    "photo_analyst": {
        "name": "识肤师",
        "capabilities": ["analyze_photo", "visual_diagnosis"],
        "required_model": "vl",
        "interruptible": True,
        "timeout_s": 30,
        "priority": 8,
    },
    "copywriter": {
        "name": "日报官",
        "capabilities": ["generate_schedule", "push_notification"],
        "required_model": "flash",
        "interruptible": True,
        "timeout_s": 20,
        "priority": 3,
    },
}
