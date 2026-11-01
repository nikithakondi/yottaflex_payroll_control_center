"""Contract tests for CSV, JSON, and Excel report serialization."""
import json
from io import BytesIO

from openpyxl import load_workbook

from payroll_validation.exports.report_exports import report_bytes


def test_report_serialization_formats():
    rows = [{"employee_id": "EMP-000001", "net_pay": 1250.5}]
    csv_data = report_bytes(rows, "csv")
    json_data = report_bytes(rows, "json")
    xlsx_data = report_bytes(rows, "xlsx", "Payroll")
    assert b"employee_id,net_pay" in csv_data
    assert json.loads(json_data)[0]["net_pay"] == 1250.5
    workbook = load_workbook(BytesIO(xlsx_data), read_only=True, data_only=True)
    assert workbook.sheetnames == ["Payroll"]
    assert workbook.active.max_row == 2
