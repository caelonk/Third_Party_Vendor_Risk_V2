"""Offline integration tests for the dev seed pipeline. Replays the saved fixture
corpus into a temporary database — no network, and no touching data/ or output/.
The synthetic business context is generated into tmp_path so the repo config is
never mutated by a test run."""
from pathlib import Path

from seed import pipeline

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
CONFIG = REPO / "config"
VENDOR_NAMES = [v["vendor_name"] for v in pipeline.read_vendors_yml(CONFIG / "vendors.yml")]


def _run(tmp_path: Path) -> dict:
    return pipeline.run(
        offline=True,
        db_path=tmp_path / "risk.db",
        output_dir=tmp_path / "out",
        fixtures_dir=FIXTURES,
        business_file=tmp_path / "business_context.csv",  # generated here (seed=42)
        vendors_file=CONFIG / "vendors.yml",
        log=lambda *a, **k: None,
    )


def test_running_twice_is_idempotent(tmp_path):
    first = _run(tmp_path)["counts"]
    second = _run(tmp_path)["counts"]  # same tmp DB, second pass
    assert first == second, "row counts changed on re-run — upserts not idempotent"
    assert first["vendors"] == 12


def test_dashboard_created_with_all_vendor_names(tmp_path):
    _run(tmp_path)
    html = (tmp_path / "out" / "dashboard.html").read_text(encoding="utf-8")
    missing = [name for name in VENDOR_NAMES if name not in html]
    assert not missing, f"dashboard missing vendor names: {missing}"


def test_dashboard_contains_scope_disclaimer(tmp_path):
    _run(tmp_path)
    html = (tmp_path / "out" / "dashboard.html").read_text(encoding="utf-8")
    assert 'A high score means "investigate," not "compromised."' in html


def test_watchlist_csv_written(tmp_path):
    _run(tmp_path)
    csv_path = tmp_path / "out" / "watchlist.csv"
    assert csv_path.exists()
    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("vendor_name,tier,contract_renewal_date")
