from pathlib import Path

from app.evals.offline import OfflineAgentAdapter
from app.evals.runner import load_cases, run_cases


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = BACKEND_ROOT / "evals" / "cases"


def test_golden_dataset_has_fifteen_cases_for_each_agent_flow() -> None:
    operating = load_cases(CASE_DIR / "operating.json")
    followup = load_cases(CASE_DIR / "followup.json")

    assert len(operating) == 15
    assert len(followup) == 15
    identifiers = [case.case_id for case in [*operating, *followup]]
    assert len(identifiers) == len(set(identifiers))
    assert all(case.fixture_refs for case in [*operating, *followup])


def test_offline_golden_cases_produce_a_safe_measurable_baseline() -> None:
    cases = [
        *load_cases(CASE_DIR / "operating.json"),
        *load_cases(CASE_DIR / "followup.json"),
    ]

    report = run_cases(cases, OfflineAgentAdapter(BACKEND_ROOT))

    assert report.summary.case_count == 30
    assert report.summary.evidence_validity == 1.0
    assert report.summary.unsupported_numeric_claim_count == 0
    assert report.summary.unsupported_normative_claim_count == 0
    assert report.summary.safety_pass_rate == 1.0
    assert report.summary.tool_precision >= 0.9
    assert report.summary.tool_recall >= 0.95
    assert report.summary.tool_exact_set_accuracy >= 0.8
