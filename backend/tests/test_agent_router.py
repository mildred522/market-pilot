from app.agents.router import detect_stage


def test_router_detects_pre_open_stage_from_opening_question():
    assert detect_stage("准备加盟奶茶店，这个位置能不能开？") == "pre_open"


def test_router_detects_operating_stage_from_revenue_question():
    assert detect_stage("最近营业额下降，问题出在哪里？") == "operating"
