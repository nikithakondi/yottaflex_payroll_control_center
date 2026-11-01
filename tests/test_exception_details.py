"""Tests for exception detail rendering and verified resolution workflow."""
from contextlib import nullcontext

import pandas as pd
import pytest

from payroll_validation.dashboard import streamlit_pages
from payroll_validation.database.connection import connect
from payroll_validation.generators.generate_dataset import generate_dataset
from payroll_validation.services.exception_service import review_exception
from payroll_validation.services.payroll_service import process_payroll_period
from payroll_validation.validators.validation_service import validate_all_payroll_runs, validate_payroll_run


class _StreamlitCapture:
    def __init__(self):
        self.metrics = {}
        self.captions = []
        self.text = []
        self.buttons = []
        self.session_state = {}
        self.view_clicks = 1

    def subheader(self, value):
        self.text.append(value)

    def columns(self, count):
        return [self] * count

    def metric(self, label, value):
        self.metrics[label] = value

    def caption(self, value):
        self.captions.append(value)

    def write(self, value):
        self.text.append(value)

    def markdown(self, value):
        self.text.append(value)

    def json(self, value):
        self.text.append(value)

    def expander(self, _label):
        return nullcontext()

    def title(self, value):
        self.text.append(value)

    def selectbox(self, _label, options, **_kwargs):
        return options[0]

    def button(self, label, key=None, on_click=None, args=(), **_kwargs):
        self.buttons.append(label)
        if key == "view-exception-details" and self.view_clicks:
            self.view_clicks -= 1
            if on_click:
                on_click(*args)
            return True
        return False

    def info(self, value):
        self.text.append(value)

    def warning(self, value):
        self.text.append(value)

    def success(self, value):
        self.text.append(value)

    def error(self, value):
        self.text.append(value)

    def dataframe(self, *_args, **_kwargs):
        return None

    def download_button(self, *_args, **_kwargs):
        return None

    def form(self, _key):
        return nullcontext()

    def text_input(self, *_args, **_kwargs):
        return ""

    def text_area(self, *_args, **_kwargs):
        return ""

    def form_submit_button(self, *_args, **_kwargs):
        return False

    def rerun(self):
        raise AssertionError("The detail-view test should not trigger a rerun")


def test_reconciliation_exception_detail_shows_expected_and_actual(monkeypatch):
    capture = _StreamlitCapture()
    monkeypatch.setattr(streamlit_pages, "st", capture)
    streamlit_pages._render_exception_detail({
        "exception_code": "PEX-2026-000005",
        "employee_reference": "EMP-000003",
        "pay_period_reference": "PP-2026-03",
        "rule_code": "PAYROLL_RECONCILIATION",
        "severity": "critical",
        "workflow_status": "open",
        "payroll_run_id": 3,
        "message": "Payroll totals do not reconcile.",
        "expected_value": '{"gross_pay":6228.38,"net_pay":5105.3}',
        "actual_value": '{"gross_pay":6253.38,"net_pay":5130.3}',
        "details_json": None,
    })

    assert "Exception details · PEX-2026-000005" in capture.text
    assert "**Exception ID:** PEX-2026-000005" in capture.text
    assert capture.metrics["Employee number"] == "EMP-000003"
    assert capture.metrics["Pay period"] == "PP-2026-03"
    assert capture.metrics["Rule code"] == "PAYROLL_RECONCILIATION"
    assert capture.metrics["Severity"] == "CRITICAL"
    assert capture.metrics["Gross pay · actual"] == "$6,253.38"
    assert capture.metrics["Net pay · actual"] == "$5,130.30"
    assert any("Status: open" in item for item in capture.captions)
    assert any("Expected $6,228.38" in item and "Difference $+25.00" in item for item in capture.captions)


def test_view_details_button_opens_selected_exception(monkeypatch):
    exception = {
        "exception_id": 5,
        "exception_code": "PEX-2026-000005",
        "employee_reference": "EMP-000003",
        "pay_period_id": 3,
        "pay_period_reference": "PP-2026-03",
        "rule_code": "PAYROLL_RECONCILIATION",
        "severity": "critical",
        "workflow_status": "open",
        "message": "Payroll totals do not reconcile.",
        "expected_value": '{"gross_pay":6228.38,"net_pay":5105.3}',
        "actual_value": '{"gross_pay":6253.38,"net_pay":5130.3}',
        "details_json": None,
        "payroll_run_id": 3,
        "entity_type": "payroll_results",
        "entity_id": "3",
        "resolution": None,
    }
    capture = _StreamlitCapture()
    detail_fetches = []
    monkeypatch.setattr(streamlit_pages, "st", capture)
    monkeypatch.setattr(streamlit_pages, "_frame", lambda *_args, **_kwargs: pd.DataFrame())

    def rows(sql, _params=()):
        if "WHERE x.exception_id=?" in sql:
            detail_fetches.append(_params[0])
            return [exception]
        if "SELECT exception_id,exception_code" in sql:
            return [{"exception_id": 5, "exception_code": "PEX-2026-000005"}]
        return []

    monkeypatch.setattr(streamlit_pages, "_rows", rows)
    streamlit_pages.exceptions()

    assert "View details" in capture.buttons
    assert capture.session_state["selected_exception_detail_id"] == 5
    assert capture.session_state["exception_detail_click_debug"] == {"registered": True, "exception_id": 5}
    assert detail_fetches == [5, 5]  # fetched in the click callback and refreshed for rendering
    assert "Exception details · PEX-2026-000005" in capture.text
    assert "**Exception ID:** PEX-2026-000005" in capture.text
    assert any("click registered" in item and "exception ID 5" in item for item in capture.captions)
    assert capture.metrics["Rule code"] == "PAYROLL_RECONCILIATION"
    assert capture.metrics["Gross pay · actual"] == "$6,253.38"
    streamlit_pages.exceptions()
    assert "Exception details · PEX-2026-000005" in capture.text


def test_view_details_shows_clear_error_for_missing_exception(monkeypatch):
    capture = _StreamlitCapture()
    monkeypatch.setattr(streamlit_pages, "st", capture)
    monkeypatch.setattr(streamlit_pages, "_frame", lambda *_args, **_kwargs: pd.DataFrame())

    def rows(sql, _params=()):
        if "WHERE x.exception_id=?" in sql:
            return []
        if "SELECT exception_id,exception_code" in sql:
            return [{"exception_id": 99, "exception_code": "PEX-2026-000099"}]
        return []

    monkeypatch.setattr(streamlit_pages, "_rows", rows)
    streamlit_pages.exceptions()
    assert any("Exception ID 99 could not be found" in value for value in capture.text)


def test_reconciliation_resolution_requires_clean_revalidation_and_reviewer(tmp_path):
    database_path = tmp_path / "exception-resolution.db"
    generate_dataset("starter", database_path=database_path, output_dir=tmp_path / "generated")
    validate_all_payroll_runs(database_path)
    with connect(database_path) as db:
        exception = dict(db.execute(
            "SELECT * FROM exceptions WHERE rule_code='PAYROLL_RECONCILIATION' ORDER BY exception_id LIMIT 1"
        ).fetchone())
        old_result = dict(db.execute(
            "SELECT * FROM payroll_results WHERE payroll_result_id=?", (exception["entity_id"],)
        ).fetchone())

    unresolved_report = validate_payroll_run(exception["payroll_run_id"], database_path)
    assert streamlit_pages._exception_still_present(unresolved_report, exception)
    with connect(database_path) as db:
        assert db.execute("SELECT workflow_status FROM exceptions WHERE exception_id=?", (exception["exception_id"],)).fetchone()[0] == "open"

    new_run = process_payroll_period(exception["pay_period_id"], database_path, actor="exception_detail_test")
    corrected_report = validate_payroll_run(new_run["payroll_run_id"], database_path, actor="exception_detail_test")
    assert not streamlit_pages._exception_still_present(corrected_report, exception)
    with connect(database_path) as db:
        assert db.execute("SELECT workflow_status FROM exceptions WHERE exception_id=?", (exception["exception_id"],)).fetchone()[0] == "open"
        preserved_result = db.execute(
            "SELECT gross_pay,net_pay FROM payroll_results WHERE payroll_result_id=?", (old_result["payroll_result_id"],)
        ).fetchone()
        assert tuple(preserved_result) == (old_result["gross_pay"], old_result["net_pay"])

    review_exception(
        exception["exception_id"], "hr-reviewer", "HR Partner", "Resolved",
        "New versioned payroll run passed reconciliation.", database_path,
    )
    with connect(database_path) as db:
        assert db.execute("SELECT workflow_status FROM exceptions WHERE exception_id=?", (exception["exception_id"],)).fetchone()[0] == "resolved"
        assert db.execute("SELECT COUNT(*) FROM exception_review_history WHERE exception_id=?", (exception["exception_id"],)).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE entity_type='exception' AND entity_id=? AND action='exception_resolved'",
            (exception["exception_code"],),
        ).fetchone()[0] == 1
