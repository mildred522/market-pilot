PRE_OPEN_KEYWORDS = ("准备", "开店", "加盟", "选址", "能不能开", "投资")
OPERATING_KEYWORDS = ("营业额", "亏损", "订单", "菜品", "差评", "经营", "不赚钱")


def detect_stage(question: str) -> str:
    if any(keyword in question for keyword in OPERATING_KEYWORDS):
        return "operating"
    if any(keyword in question for keyword in PRE_OPEN_KEYWORDS):
        return "pre_open"
    return "operating"
