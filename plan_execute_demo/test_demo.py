import unittest
from unittest.mock import patch

from plan_execute_demo.engine import run_demo
from plan_execute_demo.ingestion import inspect_csv
from plan_execute_demo.server import api_response
from plan_execute_demo.evidence import validate_findings
from plan_execute_demo.models import EvidenceFact, Finding


class PlanExecuteDemoTests(unittest.TestCase):
    def test_full_mode_runs_the_complete_whitelisted_set(self) -> None:
        report = run_demo("做一次完整经营体检", mode="full")
        self.assertEqual([item.tool for item in report.plan.items], ["revenue", "menu", "survival"])
        self.assertEqual(report.metrics["revenue"]["total_revenue"], 336.0)
        self.assertEqual(report.trace["validation"], "passed")

    def test_focused_menu_question_uses_only_menu_tool(self) -> None:
        report = run_demo("哪些菜品需要优化？")
        self.assertEqual([item.tool for item in report.plan.items], ["menu"])
        self.assertEqual(set(report.metrics), {"menu"})

    def test_validator_rejects_an_uncited_number(self) -> None:
        evidence = (EvidenceFact("E1", "metrics.revenue.total_revenue", "营收", 336.0),)
        with self.assertRaisesRegex(ValueError, "unsupported_number"):
            validate_findings((Finding("营收为999元。", ("E1",)),), evidence)

    def test_survival_failure_replans_once_to_revenue(self) -> None:
        orders = [
            {"order_id": "O1", "item_name": "A", "quantity": "1", "actual_amount": "20"}
        ]
        menu = [{"item_name": "B", "unit_cost": "5"}]
        report = run_demo("保本压力大吗？", orders=orders, menu=menu)
        self.assertEqual(set(report.metrics), {"revenue"})
        self.assertTrue(report.trace["replan"]["attempted"])
        self.assertEqual(report.trace["replan"]["replacement_tools"], ["revenue"])

    def test_chinese_headers_produce_a_mapping(self) -> None:
        inspection = inspect_csv("订单号,菜品名称,数量,实收金额\nO1,面,1,20\n", "orders")
        self.assertEqual(inspection["missing_fields"], [])
        self.assertEqual(inspection["suggested_mapping"]["order_id"], "订单号")

    def test_local_api_returns_the_default_report(self) -> None:
        status, payload = api_response("/api/analyze", {"question": "营业额是多少？"})
        self.assertEqual(int(status), 200)
        self.assertEqual(payload["plan"]["tools"][0]["tool"], "revenue")
        self.assertIn("deterministic", payload["trace"]["composition"])

    def test_llm_configuration_never_returns_the_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            status, payload = api_response(
                "/api/llm-config",
                {
                    "endpoint": "https://api.deepseek.com/chat/completions",
                    "model": "deepseek-v4-flash",
                    "api_key": "test-secret-key",
                },
            )
            self.assertEqual(int(status), 200)
            self.assertTrue(payload["configured"])
            self.assertNotIn("api_key", payload)
            self.assertNotIn("test-secret-key", str(payload))


if __name__ == "__main__":
    unittest.main()
