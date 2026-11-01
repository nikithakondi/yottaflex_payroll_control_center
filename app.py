"""YottaFlex AI local payroll control center."""
import importlib

import streamlit as st
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from payroll_validation.dashboard import streamlit_pages as views
from payroll_validation.database.init_db import initialize

# Streamlit reruns this entrypoint while imported modules remain cached by
# Python. Reload the canonical page module so the navigation table always
# binds the current Exceptions implementation instead of a stale function.
views = importlib.reload(views)

st.set_page_config(page_title="YottaFlex AI | Payroll Control Center",page_icon="💼",layout="wide",initial_sidebar_state="expanded")
st.markdown("""
<style>
  .stApp { background: #f5f7fb; }
  [data-testid="stSidebar"] { background: #101a2b; }
  [data-testid="stSidebar"] * { color: #e6edf7; }
  [data-testid="stMetric"] { background: white; border: 1px solid #e6eaf1; padding: 14px 16px; border-radius: 12px; }
  h1, h2, h3 { color: #16253c; }
</style>
""",unsafe_allow_html=True)
st.sidebar.markdown("## YottaFlex AI\n**Payroll Control Center**")
st.sidebar.caption("Local SQLite · Validation before export")
try:
    initialize()
except Exception as exc:
    st.error(f"Database initialization failed: {exc}")
    st.stop()

pages={
    "Overview": [st.Page(views.dashboard,title="Dashboard",icon="📊",default=True)],
    "Payroll data": [
        st.Page(views.employees,title="Employees",icon="👥"),
        st.Page(views.pay_groups,title="Pay Groups",icon="🏷️"),
        st.Page(views.pay_periods,title="Pay Periods",icon="🗓️"),
        st.Page(views.time_entries,title="Time Entries",icon="⏱️"),
        st.Page(views.leave_management,title="Leave Management",icon="🌴"),
        st.Page(views.allowances,title="Allowances",icon="➕"),
        st.Page(views.deductions,title="Deductions",icon="➖"),
    ],
    "Payroll controls": [
        st.Page(views.payroll_processing,title="Payroll Processing",icon="🧮"),
        st.Page(views.validation,title="Validation",icon="✅"),
        st.Page(views.exceptions,title="Exceptions",icon="🚩"),
        st.Page(views.approvals,title="Approvals",icon="📝"),
        st.Page(views.payroll_export,title="Payroll Export",icon="📤"),
    ],
    "Insights & traceability": [
        st.Page(views.audit_history,title="Audit History",icon="🧾"),
        st.Page(views.reports,title="Reports & Reconciliation",icon="📈"),
    ],
}
st.navigation(pages).run()
