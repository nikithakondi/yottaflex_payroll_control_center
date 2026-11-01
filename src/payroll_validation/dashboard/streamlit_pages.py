"""Database-backed Streamlit page renderers for the YottaFlex application."""
from datetime import date
import json

import pandas as pd
import plotly.express as px
import streamlit as st

from payroll_validation.config import DATABASE_PATH, EXPORT_DIR
from payroll_validation.database.connection import connect
from payroll_validation.database.init_db import initialize
from payroll_validation.services.records import (create_employee, update_employee, create_pay_group,
    create_pay_period, create_time_entry, set_time_approval, create_leave_record,
    create_allowance, create_deduction, set_leave_status)
from payroll_validation.services.payroll_service import process_payroll_period, approve_payroll_run, export_payroll_run
from payroll_validation.validators.validation_service import validate_payroll_run
from payroll_validation.approvals.approval_service import review_payroll_input, submit_source_correction
from payroll_validation.services.exception_service import assign_exception, review_exception
from payroll_validation.exports.report_exports import (
    reconciliation_report_rows, report_bytes, validation_report_rows,
)

def _frame(sql, params=()):
    with connect() as db: return pd.read_sql_query(sql,db,params=params)

def _rows(sql, params=()):
    with connect() as db: return [dict(r) for r in db.execute(sql,params)]

def _options(sql, label, params=()):
    rows=_rows(sql,params)
    return {f"{r[label[0]]} · {r[label[1]]}":r[label[0]] for r in rows}

def _decode_exception_value(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value

def _exception_still_present(report, exception):
    return any(
        finding.get("severity")=="critical"
        and finding.get("employee_reference")==exception["employee_reference"]
        and finding.get("pay_period_reference")==exception["pay_period_reference"]
        for finding in report["findings"]
    )

def _render_exception_detail(exception):
    st.subheader(f"Exception details · {exception['exception_code']}")
    st.write(f"**Exception ID:** {exception['exception_code']}")
    columns=st.columns(4)
    columns[0].metric("Employee number",exception["employee_reference"] or "—")
    columns[1].metric("Pay period",exception["pay_period_reference"] or "—")
    columns[2].metric("Rule code",exception["rule_code"])
    columns[3].metric("Severity",(exception["severity"] or "unknown").upper())
    st.caption(f"Status: {exception['workflow_status']} · Run: {exception['payroll_run_id']}")
    st.write("**Validation message**")
    st.write(exception["message"] or "No validation message was recorded.")

    expected=_decode_exception_value(exception["expected_value"])
    actual=_decode_exception_value(exception["actual_value"])
    if exception["rule_code"]=="PAYROLL_RECONCILIATION" and isinstance(expected,dict) and isinstance(actual,dict):
        st.markdown("**Payroll reconciliation**")
        amount_columns=st.columns(2)
        for column,label,key in ((amount_columns[0],"Gross pay","gross_pay"),(amount_columns[1],"Net pay","net_pay")):
            expected_amount=expected.get(key)
            actual_amount=actual.get(key)
            column.metric(f"{label} · actual",f"${float(actual_amount):,.2f}" if actual_amount is not None else "—")
            if expected_amount is not None and actual_amount is not None:
                column.caption(f"Expected ${float(expected_amount):,.2f} · Difference ${float(actual_amount)-float(expected_amount):+,.2f}")
    else:
        value_columns=st.columns(2)
        value_columns[0].write("**Expected value**")
        value_columns[0].json(expected) if isinstance(expected,(dict,list)) else value_columns[0].write(expected)
        value_columns[1].write("**Actual value**")
        value_columns[1].json(actual) if isinstance(actual,(dict,list)) else value_columns[1].write(actual)

    if exception["details_json"]:
        with st.expander("Validation details"):
            st.json(_decode_exception_value(exception["details_json"]))

def _select_exception_detail(exception_id):
    """Persist the selection and fetch the requested exception on button click."""
    st.session_state["selected_exception_detail_id"] = exception_id
    detail_rows = _rows(
        "SELECT x.exception_id,x.exception_code,x.employee_reference,x.pay_period_id,x.pay_period_reference,"
        "x.rule_code,x.severity,x.workflow_status,x.message,x.expected_value,x.actual_value,x.details_json,"
        "x.payroll_run_id,x.entity_type,x.entity_id,x.resolution "
        "FROM exceptions x WHERE x.exception_id=?",
        (exception_id,),
    )
    st.session_state["selected_exception_detail"] = detail_rows[0] if detail_rows else None
    st.session_state["exception_detail_click_debug"] = {
        "registered": True,
        "exception_id": exception_id,
    }
    st.session_state.pop("exception_detail_revalidation", None)

def _show_table(df, key):
    if df.empty: st.info("No records found.")
    else:
        display_df=df.copy()
        for column in display_df.columns:
            if display_df[column].map(lambda value:isinstance(value,(dict,list,tuple))).any():
                display_df[column]=display_df[column].map(lambda value:json.dumps(value,default=str) if isinstance(value,(dict,list,tuple)) else value)
        st.dataframe(display_df,use_container_width=True,hide_index=True)
        st.download_button("Download table as CSV",df.to_csv(index=False).encode(),f"{key}.csv","text/csv",key=f"dl-{key}")

def _mutate(action,success="Saved"):
    try:
        result=action()
        st.success(f"{success}. Record ID: {result}")
        st.rerun()
    except Exception as exc: st.error(str(exc))

def employees():
    st.title("Employee Management")
    search=st.text_input("Search employees by ID, name, email, department")
    sql="SELECT e.employee_id,e.employee_number,e.first_name,e.last_name,e.email,e.department,e.job_title,e.hire_date,e.employment_status,g.code AS pay_group,e.annual_salary,e.hourly_rate,CASE WHEN e.bank_account_token IS NULL OR trim(e.bank_account_token)='' THEN 'Missing' ELSE 'Present' END AS bank_details,CASE WHEN e.tax_info_token IS NULL OR trim(e.tax_info_token)='' THEN 'Missing' ELSE 'Present' END AS tax_information FROM employees e JOIN pay_groups g USING(pay_group_id)"
    if search: sql+=" WHERE e.employee_number LIKE ? OR e.first_name LIKE ? OR e.last_name LIKE ? OR e.email LIKE ? OR e.department LIKE ?"; args=tuple([f"%{search}%"]*5)
    else: args=()
    _show_table(_frame(sql+" ORDER BY e.employee_number",args),"employees")
    with st.expander("Add employee"):
        groups=_options("SELECT pay_group_id,code FROM pay_groups ORDER BY code",("pay_group_id","code"))
        with st.form("employee-add"):
            c=st.columns(3); first=c[0].text_input("First name"); last=c[1].text_input("Last name"); email=c[2].text_input("Email")
            c=st.columns(3); dept=c[0].text_input("Department"); title=c[1].text_input("Job title"); hire=c[2].date_input("Hire date",value=date.today())
            c=st.columns(3); salary=c[0].number_input("Annual salary",min_value=0.0,value=72000.0); group=c[1].selectbox("Pay group",list(groups)); bank=c[2].text_input("Synthetic bank token")
            tax=st.text_input("Tax information token")
            if st.form_submit_button("Create employee"):
                if not all((first,last,email,dept,title)): st.error("Complete all required fields")
                else: _mutate(lambda:create_employee({"first_name":first,"last_name":last,"email":email,"department":dept,"job_title":title,"hire_date":hire.isoformat(),"annual_salary":salary,"pay_group_id":groups[group],"bank_account_token":bank or None,"tax_info_token":tax or None}))
    with st.expander("Update employee status or details"):
        ids=_options("SELECT employee_id,employee_number FROM employees ORDER BY employee_number",("employee_id","employee_number"))
        if ids:
            with st.form("employee-update"):
                chosen=st.selectbox("Employee",list(ids)); status=st.selectbox("Employment status",["active","on_leave","terminated"]); department=st.text_input("Department (optional)")
                if st.form_submit_button("Save employee update"):
                    changes={"employment_status":status}
                    if department: changes["department"]=department
                    _mutate(lambda:update_employee(ids[chosen],changes))

def pay_groups():
    st.title("Pay Group Management"); _show_table(_frame("SELECT * FROM pay_groups ORDER BY code"),"pay-groups")
    with st.expander("Create pay group"):
        with st.form("pay-group"):
            c=st.columns(3); code=c[0].text_input("Code"); name=c[1].text_input("Name"); frequency=c[2].selectbox("Frequency",["monthly","semi_monthly","biweekly","weekly"])
            c=st.columns(3); currency=c[0].text_input("Currency",value="USD",max_chars=3); hours=c[1].number_input("Standard hours",min_value=1.0,value=40.0); max_hours=c[2].number_input("Period maximum hours",min_value=1.0,value=200.0)
            multiplier=st.number_input("Overtime multiplier",min_value=1.0,value=1.5)
            if st.form_submit_button("Create pay group"):
                _mutate(lambda:create_pay_group({"code":code,"name":name,"pay_frequency":frequency,"currency":currency,"standard_hours":hours,"max_period_hours":max_hours,"overtime_multiplier":multiplier}))

def pay_periods():
    st.title("Pay Period Management"); _show_table(_frame("SELECT p.pay_period_id,p.pay_period_code,g.code AS pay_group,p.period_start,p.period_end,p.payment_date,p.status FROM pay_periods p JOIN pay_groups g USING(pay_group_id) ORDER BY p.period_start DESC"),"pay-periods")
    groups=_options("SELECT pay_group_id,code FROM pay_groups ORDER BY code",("pay_group_id","code"))
    with st.expander("Create pay period"):
        with st.form("period-create"):
            c=st.columns(3); group=c[0].selectbox("Pay group",list(groups)); code=c[1].text_input("Period ID (e.g. PP-2026-04)"); start=c[2].date_input("Start date")
            c=st.columns(2); end=c[0].date_input("End date"); payment=c[1].date_input("Payment date")
            if st.form_submit_button("Create pay period"):
                _mutate(lambda:create_pay_period({"pay_group_id":groups[group],"pay_period_code":code,"period_start":start.isoformat(),"period_end":end.isoformat(),"payment_date":payment.isoformat()}))

def time_entries():
    st.title("Time Entry Management")
    period=st.selectbox("Pay period",["All"]+list(_options("SELECT pay_period_id,pay_period_code FROM pay_periods ORDER BY period_start DESC",("pay_period_id","pay_period_code"))))
    query="SELECT t.time_entry_id,t.time_entry_code,e.employee_number,p.pay_period_code,t.work_date,t.regular_hours,t.overtime_hours,t.status,t.approval_status,t.submission_type,t.source FROM time_entries t JOIN employees e USING(employee_id) JOIN pay_periods p USING(pay_period_id)"
    _show_table(_frame(query+(" WHERE t.pay_period_id=?" if period!="All" else "")+" ORDER BY t.work_date DESC LIMIT 2000",(_options("SELECT pay_period_id,pay_period_code FROM pay_periods",("pay_period_id","pay_period_code"))[period],) if period!="All" else ()),"time-entries")
    employees_map=_options("SELECT employee_id,employee_number FROM employees WHERE employment_status='active' ORDER BY employee_number",("employee_id","employee_number")); periods=_options("SELECT pay_period_id,pay_period_code FROM pay_periods WHERE status IN ('open','processing') ORDER BY period_start DESC",("pay_period_id","pay_period_code"))
    with st.expander("Submit time entry"):
        with st.form("time-create"):
            c=st.columns(4); employee=c[0].selectbox("Employee",list(employees_map)); pp=c[1].selectbox("Pay period",list(periods)); work=c[2].date_input("Work date"); regular=c[3].number_input("Regular hours",min_value=0.0,max_value=24.0,value=8.0)
            overtime=st.number_input("Overtime hours",min_value=0.0,max_value=24.0,value=0.0)
            if st.form_submit_button("Submit time"):
                _mutate(lambda:create_time_entry({"employee_id":employees_map[employee],"pay_period_id":periods[pp],"work_date":work.isoformat(),"regular_hours":regular,"overtime_hours":overtime}))
    pending=_options("SELECT time_entry_id,time_entry_code FROM time_entries WHERE approval_status='pending' ORDER BY time_entry_id DESC LIMIT 1000",("time_entry_id","time_entry_code"))
    if pending:
        with st.form("time-review"):
            selected=st.selectbox("Pending entry",list(pending)); decision=st.selectbox("Manager decision",["approved","rejected"])
            if st.form_submit_button("Record time decision"):
                try: set_time_approval(pending[selected],decision,"Manager"); st.success("Time decision recorded."); st.rerun()
                except Exception as exc: st.error(str(exc))

def leave_management():
    st.title("Leave Management"); _show_table(_frame("SELECT l.leave_id,e.employee_number,p.pay_period_code,l.leave_type,l.start_date,l.end_date,l.hours,l.status,l.supersedes_leave_id FROM leave_records l JOIN employees e USING(employee_id) JOIN pay_periods p USING(pay_period_id) ORDER BY l.start_date DESC LIMIT 2000"),"leave-records")
    emp=_options("SELECT employee_id,employee_number FROM employees WHERE employment_status='active' ORDER BY employee_number",("employee_id","employee_number")); periods=_options("SELECT pay_period_id,pay_period_code FROM pay_periods ORDER BY period_start DESC",("pay_period_id","pay_period_code"))
    with st.expander("Submit leave"):
        with st.form("leave-create"):
            c=st.columns(4); employee=c[0].selectbox("Employee",list(emp)); pp=c[1].selectbox("Pay period",list(periods)); kind=c[2].selectbox("Leave type",["paid","unpaid"]); hours=c[3].number_input("Hours",min_value=0.0,value=8.0)
            c=st.columns(2); start=c[0].date_input("Start date"); end=c[1].date_input("End date")
            if st.form_submit_button("Submit leave"):
                _mutate(lambda:create_leave_record({"employee_id":emp[employee],"pay_period_id":periods[pp],"leave_type":kind,"start_date":start.isoformat(),"end_date":end.isoformat(),"hours":hours}))
    pending=_options("SELECT leave_id,'Leave #' || leave_id || ' · ' || leave_type || ' · ' || hours || 'h' AS label FROM leave_records WHERE status='pending' ORDER BY leave_id DESC LIMIT 1000",("leave_id","label"))
    if pending:
        with st.form("leave-review"):
            item=st.selectbox("Pending leave",list(pending)); decision=st.selectbox("Manager decision",["approved","rejected"])
            if st.form_submit_button("Record leave decision"):
                try: set_leave_status(pending[item],decision,"Manager"); st.success("Leave decision recorded"); st.rerun()
                except Exception as exc: st.error(str(exc))

def allowances():
    st.title("Allowance Management"); _show_table(_frame("SELECT a.allowance_id,a.allowance_code,e.employee_number,p.pay_period_code,a.allowance_type,a.amount,a.taxable,a.source_reference,a.submission_type,a.supersedes_allowance_id FROM allowances a JOIN employees e USING(employee_id) JOIN pay_periods p USING(pay_period_id) ORDER BY a.allowance_id DESC LIMIT 2000"),"allowances")
    emp=_options("SELECT employee_id,employee_number FROM employees WHERE employment_status='active' ORDER BY employee_number",("employee_id","employee_number")); periods=_options("SELECT pay_period_id,pay_period_code FROM pay_periods ORDER BY period_start DESC",("pay_period_id","pay_period_code"))
    with st.expander("Add allowance"):
        with st.form("allowance-create"):
            c=st.columns(4); employee=c[0].selectbox("Employee",list(emp)); pp=c[1].selectbox("Pay period",list(periods)); kind=c[2].selectbox("Type",["commute","meal","home_office","shift","bonus","other"]); amount=c[3].number_input("Amount",min_value=0.0,value=50.0)
            taxable=st.checkbox("Taxable",value=True); desc=st.text_input("Description")
            if st.form_submit_button("Add allowance"):
                _mutate(lambda:create_allowance({"employee_id":emp[employee],"pay_period_id":periods[pp],"allowance_type":kind,"amount":amount,"taxable":int(taxable),"description":desc}))

def deductions():
    st.title("Deduction Management"); _show_table(_frame("SELECT d.deduction_id,d.deduction_code,e.employee_number,p.pay_period_code,d.deduction_type,d.amount,d.pre_tax,d.leave_id,d.source_reference,d.submission_type,d.supersedes_deduction_id FROM deductions d JOIN employees e USING(employee_id) JOIN pay_periods p USING(pay_period_id) ORDER BY d.deduction_id DESC LIMIT 2000"),"deductions")
    emp=_options("SELECT employee_id,employee_number FROM employees WHERE employment_status='active' ORDER BY employee_number",("employee_id","employee_number")); periods=_options("SELECT pay_period_id,pay_period_code FROM pay_periods ORDER BY period_start DESC",("pay_period_id","pay_period_code"))
    with st.expander("Add deduction"):
        with st.form("deduction-create"):
            c=st.columns(4); employee=c[0].selectbox("Employee",list(emp)); pp=c[1].selectbox("Pay period",list(periods)); kind=c[2].selectbox("Type",["tax_withholding","retirement","health_insurance","unpaid_leave","loan","other"]); amount=c[3].number_input("Amount",min_value=0.0,value=50.0)
            pretax=st.checkbox("Pre-tax",value=False); desc=st.text_input("Description")
            if st.form_submit_button("Add deduction"):
                _mutate(lambda:create_deduction({"employee_id":emp[employee],"pay_period_id":periods[pp],"deduction_type":kind,"amount":amount,"pre_tax":int(pretax),"description":desc}))

def payroll_processing():
    st.title("Payroll Processing"); periods=_options("SELECT pay_period_id,pay_period_code FROM pay_periods ORDER BY period_start DESC",("pay_period_id","pay_period_code"))
    selected=st.selectbox("Pay period to process",list(periods))
    if st.button("Create payroll run from source records",type="primary"):
        try: st.session_state["created_run"]=process_payroll_period(periods[selected]); st.success(f"Created payroll run {st.session_state['created_run']['payroll_run_id']} with source-derived totals")
        except Exception as exc: st.error(str(exc))
    _show_table(_frame("SELECT r.payroll_run_id,p.pay_period_code,r.run_number,r.status,r.created_at,r.created_by,COUNT(pr.payroll_result_id) AS employee_results,ROUND(COALESCE(SUM(pr.gross_pay),0),2) AS gross_pay,ROUND(COALESCE(SUM(pr.net_pay),0),2) AS net_pay FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) LEFT JOIN payroll_results pr USING(payroll_run_id) GROUP BY r.payroll_run_id ORDER BY r.payroll_run_id DESC"),"payroll-runs")

def validation():
    st.title("Payroll Validation"); runs=_options("SELECT r.payroll_run_id,p.pay_period_code || ' · Run ' || r.run_number AS label FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) ORDER BY r.payroll_run_id DESC",("payroll_run_id","label"))
    if not runs: st.info("Process a payroll period to create a run for validation."); return
    selected=st.selectbox("Payroll run",list(runs))
    if st.button("Run all validation rules",type="primary"):
        try: st.session_state["validation_report"]=validate_payroll_run(runs[selected])
        except Exception as exc: st.error(str(exc))
    report=st.session_state.get("validation_report")
    if report and report["payroll_run_id"]==runs[selected]:
        c=st.columns(4); c[0].metric("Records checked",report["records_checked"]); c[1].metric("Valid",report["valid_records"]); c[2].metric("Invalid",report["invalid_records"]); c[3].metric("Exceptions",report["total_exceptions"])
        st.success("Export ready" if report["export_ready"] else "Approval/export blocked by critical validation findings")
        if report["exceptions_by_category"]: st.plotly_chart(px.bar(pd.DataFrame([{"Rule":k,"Exceptions":v} for k,v in report["exceptions_by_category"].items()]),x="Rule",y="Exceptions",title="Findings by validation rule"),use_container_width=True)
        _show_table(pd.DataFrame(report["findings"]),"validation-findings")
        validation_rows=validation_report_rows(runs[selected],DATABASE_PATH)
        fmt=st.selectbox("Validation report format",["csv","xlsx"],key="validation-report-format")
        st.download_button("Download validation report",report_bytes(validation_rows,fmt,"Validation"),
                           f"validation-run-{runs[selected]}.{fmt}",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt=="xlsx" else "text/csv")

def exceptions():
    st.title("Exception Management")
    status=st.selectbox("Workflow status",["All","open","under_review","resolved","rejected"])
    sql="SELECT x.exception_id,x.exception_code,p.pay_period_code,e.employee_number,x.rule_code,vr.name AS category,x.severity,x.message,x.expected_value,x.actual_value,x.workflow_status,x.detected_at,x.resolution FROM exceptions x LEFT JOIN pay_periods p USING(pay_period_id) LEFT JOIN employees e USING(employee_id) LEFT JOIN validation_rules vr USING(validation_rule_id)"
    df=_frame(sql+(" WHERE x.workflow_status=?" if status!="All" else "")+" ORDER BY x.detected_at DESC",(status,) if status!="All" else ())
    detail_options=_rows("SELECT exception_id,exception_code FROM exceptions ORDER BY detected_at DESC,exception_id DESC")
    if detail_options:
        codes_by_id={row["exception_id"]:row["exception_code"] for row in detail_options}
        selected_id=st.selectbox(
            "Exception ID",
            list(codes_by_id),
            format_func=lambda exception_id:codes_by_id.get(exception_id,str(exception_id)),
            key="exception-detail-picker",
        )
        st.button(
            "View details",
            key="view-exception-details",
            on_click=_select_exception_detail,
            args=(selected_id,),
        )
        detail_id=st.session_state.get("selected_exception_detail_id")
        if detail_id is not None:
            click_debug=st.session_state.get("exception_detail_click_debug",{})
            if click_debug.get("registered"):
                st.caption(
                    f"Debug: View details click registered · selected exception ID {click_debug['exception_id']}"
                )
            detail_rows=_rows(
                "SELECT x.exception_id,x.exception_code,x.employee_reference,x.pay_period_id,x.pay_period_reference,"
                "x.rule_code,x.severity,x.workflow_status,x.message,x.expected_value,x.actual_value,x.details_json,"
                "x.payroll_run_id,x.entity_type,x.entity_id,x.resolution "
                "FROM exceptions x WHERE x.exception_id=?",
                (detail_id,),
            )
            if detail_rows:
                exception=detail_rows[0]
                _render_exception_detail(exception)
                st.markdown("**Correction and revalidation**")
                if exception["rule_code"]=="PAYROLL_RECONCILIATION":
                    st.info("Recalculate from current source records to create a new versioned payroll run. The original run and result are preserved.")
                    action_label="Recalculate payroll from source and validate"
                    action_key=f"recalculate-exception-{exception['exception_id']}"
                else:
                    st.info("Submit an append-only source correction from the Approvals page. The original submission and audit history are preserved.")
                    action_label="Revalidate latest payroll run for this period"
                    action_key=f"revalidate-exception-{exception['exception_id']}"

                if st.button(action_label,key=action_key):
                    try:
                        if exception["rule_code"]=="PAYROLL_RECONCILIATION":
                            new_run=process_payroll_period(exception["pay_period_id"],DATABASE_PATH,actor="streamlit_exception_review")
                            run_id=new_run["payroll_run_id"]
                        else:
                            latest=_rows(
                                "SELECT payroll_run_id FROM payroll_runs WHERE pay_period_id=? ORDER BY run_number DESC LIMIT 1",
                                (exception["pay_period_id"],),
                            )
                            if not latest:
                                raise ValueError("No payroll run exists for this exception's pay period")
                            run_id=latest[0]["payroll_run_id"]
                        report=validate_payroll_run(run_id,DATABASE_PATH,actor="streamlit_exception_review")
                        still_detected=_exception_still_present(report,exception)
                        st.session_state["exception_detail_revalidation"]={
                            "exception_id":exception["exception_id"],
                            "run_id":run_id,
                            "still_detected":still_detected,
                        }
                        st.rerun()
                    except Exception as error:
                        st.error(f"Correction or revalidation failed: {error}")

                revalidation=st.session_state.get("exception_detail_revalidation",{})
                if revalidation.get("exception_id")==exception["exception_id"]:
                    if revalidation["still_detected"]:
                        st.warning(f"A critical finding remains for this employee and pay period in payroll run {revalidation['run_id']}. The exception remains unresolved.")
                    elif exception["workflow_status"] in {"open","under_review","rejected"}:
                        st.success(f"The issue was not detected in payroll run {revalidation['run_id']}. The exception remains open until a reviewer confirms resolution.")
                        with st.form(f"exception-resolution-{exception['exception_id']}"):
                            role=st.selectbox("Reviewer role",["Manager","HR Partner","IT/Operations Partner","System Administrator"],key=f"exception-resolution-role-{exception['exception_id']}")
                            reviewer=st.text_input("Reviewer ID",key=f"exception-resolution-reviewer-{exception['exception_id']}")
                            comments=st.text_area("Resolution comments",key=f"exception-resolution-comments-{exception['exception_id']}")
                            if st.form_submit_button("Resolve after verified correction",key=f"exception-resolution-submit-{exception['exception_id']}"):
                                try:
                                    review_exception(exception["exception_id"],reviewer or role,role,"Resolved",comments,DATABASE_PATH)
                                    st.session_state.pop("exception_detail_revalidation",None)
                                    st.success("Exception resolved and audit history recorded.")
                                    st.rerun()
                                except Exception as error:
                                    st.error(str(error))
            else:
                st.error(f"Exception ID {detail_id} could not be found. Refresh the page and select an existing exception.")

    _show_table(df,"exceptions")
    ids=_options("SELECT exception_id,exception_code FROM exceptions WHERE workflow_status IN ('open','under_review','rejected') ORDER BY exception_id",("exception_id","exception_code"))
    if not ids: return
    roles=["Manager","HR Partner","IT/Operations Partner","System Administrator"]
    with st.expander("Assign exception"):
        with st.form("exception-assign"):
            c=st.columns(4); exc=c[0].selectbox("Exception",list(ids)); assignee=c[1].text_input("Assignee ID"); assignee_role=c[2].selectbox("Assignee role",["Manager","HR Partner","IT/Operations Partner","System Administrator"]); assigner=c[3].selectbox("Assigning role",roles)
            comment=st.text_input("Assignment comment")
            if st.form_submit_button("Assign for review"):
                try: assign_exception(ids[exc],assignee,assignee_role,"streamlit-reviewer",assigner,comments=comment); st.success("Exception assigned"); st.rerun()
                except Exception as error: st.error(str(error))
    with st.expander("Review exception"):
        with st.form("exception-review"):
            c=st.columns(3); exc=c[0].selectbox("Exception to review",list(ids)); role=c[1].selectbox("Reviewer role",roles); status=c[2].selectbox("New status",["Under Review","Rejected"])
            reviewer=st.text_input("Reviewer ID"); comment=st.text_area("Comments",height=80)
            if st.form_submit_button("Save exception review"):
                try: review_exception(ids[exc],reviewer or role,role,status,comment); st.success("Review action recorded"); st.rerun()
                except Exception as error: st.error(str(error))

def approvals():
    st.title("Approval Management")
    runs=_options("SELECT r.payroll_run_id,p.pay_period_code || ' · Run ' || r.run_number AS label FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) WHERE r.status IN ('validated','processed') ORDER BY r.payroll_run_id DESC",("payroll_run_id","label"))
    if not runs: st.info("No runs are available for review. Validate a run first."); return
    run_label=st.selectbox("Run",list(runs)); run_id=runs[run_label]
    inputs=_options("SELECT pi.payroll_input_id,pi.payroll_input_code FROM payroll_inputs pi JOIN payroll_run_inputs ri ON ri.employee_id=pi.employee_id AND ri.pay_period_id=pi.pay_period_id WHERE ri.payroll_run_id=? ORDER BY pi.payroll_input_code",("payroll_input_id","payroll_input_code"),(run_id,))
    if not inputs: st.warning("No payroll inputs are attached to this run."); return
    with st.form("input-review"):
        c=st.columns(4); item=c[0].selectbox("Payroll input",list(inputs)); reviewer_role=c[1].selectbox("Reviewer role",["Manager","HR Partner"]); decision=c[2].selectbox("Decision",["Approved","Rejected","Correction Required"]); reviewer=c[3].text_input("Reviewer ID",value="reviewer")
        comments=st.text_input("Comments")
        if st.form_submit_button("Record decision"):
            try: review_payroll_input(inputs[item],reviewer,reviewer_role,decision,comments,database_path=DATABASE_PATH,payroll_run_id=run_id); st.success("Approval decision recorded"); st.rerun()
            except Exception as exc: st.error(str(exc))
    st.subheader("Append-only correction and revalidation")
    entity=st.selectbox("Source record type",["time_entry","leave_record","allowance","deduction"])
    table,pk={"time_entry":("time_entries","time_entry_id"),"leave_record":("leave_records","leave_id"),"allowance":("allowances","allowance_id"),"deduction":("deductions","deduction_id")}[entity]
    selected_input_id=inputs[item]
    source_rows=_rows(f"SELECT s.{pk} AS id,CAST(s.{pk} AS TEXT) AS label FROM {table} s JOIN payroll_run_inputs ri ON ri.employee_id=s.employee_id AND ri.pay_period_id=s.pay_period_id JOIN payroll_inputs pi ON pi.employee_id=ri.employee_id AND pi.pay_period_id=ri.pay_period_id WHERE ri.payroll_run_id=? AND pi.payroll_input_id=? ORDER BY s.{pk} DESC LIMIT 1000",(run_id,selected_input_id))
    if source_rows:
        selected=st.selectbox("Source record ID",[r["label"] for r in source_rows])
        with st.form("source-correction"):
            actor=st.text_input("Submitter ID",value="employee"); changes={}
            if entity=="time_entry": changes["regular_hours"]=st.number_input("Correct regular hours",min_value=0.0,value=8.0); changes["overtime_hours"]=st.number_input("Correct overtime hours",min_value=0.0,value=0.0)
            elif entity in {"allowance","deduction"}: changes["amount"]=st.number_input("Correct amount",min_value=0.0,value=50.0)
            else:
                changes["hours"]=st.number_input("Correct leave hours",min_value=0.0,value=8.0); changes["status"]=st.selectbox("Corrected leave status",["approved","pending"])
            note=st.text_input("Correction note")
            if st.form_submit_button("Append correction and revalidate"):
                try:
                    source_id=next(r["id"] for r in source_rows if r["label"]==selected)
                    result=submit_source_correction(selected_input_id,entity,source_id,changes,actor,reviewer_role="Employee",comments=note,payroll_run_id=run_id)
                    st.success(f"Correction appended. New run {result['payroll_run']['payroll_run_id']} revalidated; export ready={result['validation']['export_ready']}")
                except Exception as exc: st.error(str(exc))
    st.subheader("Approval history")
    status_df=_frame("SELECT pi.payroll_input_code,COALESCE((SELECT ah.new_status FROM approval_history ah WHERE ah.payroll_run_id=? AND ah.payroll_input_id=pi.payroll_input_id ORDER BY ah.approval_id DESC LIMIT 1),'pending') AS approval_status FROM payroll_run_inputs ri JOIN payroll_inputs pi ON pi.employee_id=ri.employee_id AND pi.pay_period_id=ri.pay_period_id WHERE ri.payroll_run_id=? ORDER BY pi.payroll_input_code",(run_id,run_id))
    st.caption(f"{int((status_df.approval_status=='approved').sum())} of {len(status_df)} payroll inputs approved")
    roles=["Manager","HR Partner"]
    with st.form("run-final-approval"):
        c=st.columns(3); role=c[0].selectbox("Final approver role",roles); actor=c[1].text_input("Final reviewer ID",value="reviewer"); note=c[2].text_input("Run approval comments")
        if st.form_submit_button("Approve fully reviewed payroll run"):
            try: approve_payroll_run(run_id,actor,DATABASE_PATH,note,role,require_explicit_input_approval=True); st.success("Payroll run approved; revalidation passed."); st.rerun()
            except Exception as exc: st.error(str(exc))
    _show_table(_frame("SELECT ah.approval_id,pi.payroll_input_code,ah.reviewer_id,ah.reviewer_role,ah.previous_status,ah.new_status,ah.action_type,ah.action_timestamp,ah.comments,ah.exception_id FROM approval_history ah JOIN payroll_inputs pi USING(payroll_input_id) WHERE ah.payroll_run_id=? ORDER BY ah.approval_id DESC",(run_id,)),"approval-history")

def payroll_export():
    st.title("Payroll Export")
    runs=_options("SELECT r.payroll_run_id,p.pay_period_code || ' · Run ' || r.run_number AS label FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) WHERE r.status='approved' ORDER BY r.payroll_run_id DESC",("payroll_run_id","label"))
    if not runs: st.info("No approved runs are available. Resolve findings, validate, and approve a run first."); return
    chosen=st.selectbox("Approved payroll run",list(runs)); fmt=st.radio("Format",["csv","json","xlsx"],horizontal=True)
    if st.button("Create payroll export",type="primary"):
        try: st.session_state["last_export"]=export_payroll_run(runs[chosen],database_path=DATABASE_PATH,actor="streamlit_user",output_format=fmt); st.success("Export created and recorded.")
        except Exception as exc: st.error(str(exc))
    result=st.session_state.get("last_export")
    if result:
        path=result["path"]
        st.json(result["summary"])
        try: st.download_button(f"Download {result['format'].upper()} file",open(path,"rb").read(),path.split("\\")[-1],key="export-download")
        except OSError: st.warning("Export file is not available on disk.")
    _show_table(_frame("SELECT export_id,payroll_run_id,format,exported_by,exported_at,record_count,checksum,file_path FROM payroll_exports ORDER BY export_id DESC"),"export-history")

def audit_history():
    st.title("Audit History"); entity=st.text_input("Filter entity type"); action=st.text_input("Filter action")
    where=[]; params=[]
    if entity: where.append("entity_type LIKE ?"); params.append(f"%{entity}%")
    if action: where.append("action LIKE ?"); params.append(f"%{action}%")
    sql="SELECT audit_event_id,entity_type,entity_id,action,actor,occurred_at,before_json,after_json FROM audit_events"+(" WHERE "+" AND ".join(where) if where else "")+" ORDER BY audit_event_id DESC LIMIT 5000"
    _show_table(_frame(sql,params),"audit-history")

def reports():
    st.title("Reports and Reconciliation")
    periods=_options("SELECT pay_period_id,pay_period_code FROM pay_periods ORDER BY period_start DESC",("pay_period_id","pay_period_code"))
    if not periods: st.info("No pay periods found."); return
    period=st.selectbox("Pay period",list(periods)); period_id=periods[period]
    departments={row["label"]:row["label"] for row in _rows("SELECT DISTINCT department AS label FROM employees ORDER BY department")}
    department_filter=st.selectbox("Department",["All departments",*departments],key="reconciliation-department")
    runs=_options("SELECT payroll_run_id,'Run ' || run_number || ' · ' || status AS label FROM payroll_runs WHERE pay_period_id=? ORDER BY run_number DESC",("payroll_run_id","label"),(period_id,))
    if runs:
        run=st.selectbox("Run to reconcile",list(runs)); reconciliation_rows=reconciliation_report_rows(runs[run],DATABASE_PATH)
        visible_rows=reconciliation_rows if department_filter=="All departments" else [row for row in reconciliation_rows if row["department"]==department_filter]
        matched=sum(row["status"]=="Match" for row in visible_rows); mismatched=len(visible_rows)-matched
        summary=st.columns(4); summary[0].metric("Records checked",len(visible_rows)); summary[1].metric("Matching",matched); summary[2].metric("Mismatching",mismatched); summary[3].metric("Total gross difference",f"{sum(row['gross_difference'] for row in visible_rows):,.2f}")
        _show_table(pd.DataFrame(visible_rows),"reconciliation")
        fmt=st.selectbox("Reconciliation report format",["csv","xlsx"],key="reconciliation-report-format")
        st.download_button("Download reconciliation report",report_bytes(visible_rows,fmt,"Reconciliation"),
                           f"reconciliation-run-{runs[run]}.{fmt}",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt=="xlsx" else "text/csv")
        departments_df=_frame("SELECT e.department,ROUND(SUM(pr.gross_pay),2) AS gross_pay,ROUND(SUM(pr.net_pay),2) AS net_pay FROM payroll_results pr JOIN employees e USING(employee_id) WHERE pr.payroll_run_id=? GROUP BY e.department ORDER BY gross_pay DESC",(runs[run],))
        if not departments_df.empty: st.plotly_chart(px.bar(departments_df,x="department",y=["gross_pay","net_pay"],barmode="group",title="Department payroll comparison"),use_container_width=True)
        st.subheader("Reconciliation history")
        _show_table(_frame("SELECT audit_event_id,occurred_at,actor,after_json AS reconciliation_summary FROM audit_events WHERE entity_type='payroll_run' AND entity_id=? AND action='reconciliation_completed' ORDER BY audit_event_id DESC LIMIT 20",(str(runs[run]),)),"reconciliation-history")
    department_sql="" if department_filter=="All departments" else " AND e.department=?"
    params=(period_id,) if not department_sql else (period_id,departments[department_filter])
    _show_table(_frame("SELECT p.pay_period_code,r.run_number,r.status,e.department,COUNT(pr.payroll_result_id) AS employees,ROUND(SUM(pr.gross_pay),2) AS gross_pay,ROUND(SUM(pr.allowance_total),2) AS allowances,ROUND(SUM(pr.deduction_total),2) AS deductions,ROUND(SUM(pr.net_pay),2) AS net_pay FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) JOIN payroll_results pr USING(payroll_run_id) JOIN employees e USING(employee_id) WHERE p.pay_period_id=?"+department_sql+" GROUP BY r.payroll_run_id,e.department ORDER BY r.run_number DESC,e.department",params),"period-payroll-report")

def dashboard():
    st.title("YottaFlex AI · Payroll Control Center")
    st.caption("Local payroll processing, data-quality controls, exception review and export readiness")
    metrics=_rows("SELECT (SELECT COUNT(*) FROM employees) AS employees,(SELECT COALESCE(SUM(gross_pay),0) FROM payroll_results pr WHERE pr.payroll_run_id IN (SELECT MAX(payroll_run_id) FROM payroll_runs GROUP BY pay_period_id)) AS gross_pay,(SELECT COALESCE(SUM(allowance_total),0) FROM payroll_results pr WHERE pr.payroll_run_id IN (SELECT MAX(payroll_run_id) FROM payroll_runs GROUP BY pay_period_id)) AS allowances,(SELECT COALESCE(SUM(deduction_total),0) FROM payroll_results pr WHERE pr.payroll_run_id IN (SELECT MAX(payroll_run_id) FROM payroll_runs GROUP BY pay_period_id)) AS deductions,(SELECT COUNT(*) FROM exceptions WHERE workflow_status IN ('open','under_review','rejected')) AS open_exceptions,(SELECT COUNT(*) FROM payroll_exports) AS exports,(SELECT COALESCE(SUM(record_count),0) FROM payroll_exports) AS exported_records,(SELECT COUNT(*) FROM payroll_run_inputs ri JOIN payroll_runs r USING(payroll_run_id) WHERE r.payroll_run_id=(SELECT MAX(r2.payroll_run_id) FROM payroll_runs r2 WHERE r2.pay_period_id=r.pay_period_id) AND EXISTS(SELECT 1 FROM audit_events ae WHERE ae.entity_type='payroll_run' AND ae.entity_id=CAST(r.payroll_run_id AS TEXT) AND ae.action='payroll_validation_completed') AND r.status IN ('processed','validated')) AS checked_inputs,(SELECT COUNT(*) FROM payroll_run_inputs ri JOIN payroll_runs r USING(payroll_run_id) WHERE r.payroll_run_id=(SELECT MAX(r2.payroll_run_id) FROM payroll_runs r2 WHERE r2.pay_period_id=r.pay_period_id) AND EXISTS(SELECT 1 FROM audit_events ae WHERE ae.entity_type='payroll_run' AND ae.entity_id=CAST(r.payroll_run_id AS TEXT) AND ae.action='payroll_validation_completed') AND r.status IN ('processed','validated') AND NOT EXISTS(SELECT 1 FROM exceptions x WHERE x.payroll_run_id=r.payroll_run_id AND x.employee_id=ri.employee_id AND x.severity='critical' AND x.workflow_status IN ('open','under_review','rejected'))) AS valid_inputs,(SELECT COUNT(*) FROM payroll_run_inputs ri JOIN payroll_runs r USING(payroll_run_id) WHERE r.payroll_run_id=(SELECT MAX(r2.payroll_run_id) FROM payroll_runs r2 WHERE r2.pay_period_id=r.pay_period_id) AND EXISTS(SELECT 1 FROM audit_events ae WHERE ae.entity_type='payroll_run' AND ae.entity_id=CAST(r.payroll_run_id AS TEXT) AND ae.action='payroll_validation_completed') AND r.status IN ('processed','validated') AND EXISTS(SELECT 1 FROM exceptions x WHERE x.payroll_run_id=r.payroll_run_id AND x.employee_id=ri.employee_id AND x.severity='critical' AND x.workflow_status IN ('open','under_review','rejected'))) AS invalid_inputs,(SELECT COUNT(*) FROM payroll_run_inputs ri JOIN payroll_runs r USING(payroll_run_id) WHERE r.payroll_run_id=(SELECT MAX(r2.payroll_run_id) FROM payroll_runs r2 WHERE r2.pay_period_id=r.pay_period_id) AND EXISTS(SELECT 1 FROM audit_events ae WHERE ae.entity_type='payroll_run' AND ae.entity_id=CAST(r.payroll_run_id AS TEXT) AND ae.action='payroll_validation_completed') AND r.status IN ('processed','validated') AND COALESCE((SELECT ah.new_status FROM approval_history ah WHERE ah.payroll_run_id=r.payroll_run_id AND ah.payroll_input_id=(SELECT pi.payroll_input_id FROM payroll_inputs pi WHERE pi.employee_id=ri.employee_id AND pi.pay_period_id=ri.pay_period_id) ORDER BY ah.approval_id DESC LIMIT 1),'pending')='pending') AS pending_approvals")
    m=metrics[0]
    cols=st.columns(4)
    for col,label,val in zip(cols,["Employees","Gross payroll","Allowances","Deductions"],[m["employees"],m["gross_pay"],m["allowances"],m["deductions"]]): col.metric(label,f"{val:,.0f}" if isinstance(val,(int,float)) else val)
    cols=st.columns(4)
    for col,label,val in zip(cols,["Valid payroll inputs","Invalid payroll inputs","Pending approvals","Open exceptions"],[m["valid_inputs"],m["invalid_inputs"],m["pending_approvals"],m["open_exceptions"]]): col.metric(label,f"{val:,}")
    st.caption(f"Exported records: {m['exported_records']:,} across {m['exports']:,} file(s) · Validation metrics reflect the latest run per period after validation has been executed.")
    record_summary=_rows("SELECT (SELECT COUNT(*) FROM payroll_results pr WHERE pr.payroll_run_id IN (SELECT MAX(payroll_run_id) FROM payroll_runs GROUP BY pay_period_id)) AS payroll_records,(SELECT COUNT(*) FROM approval_history ah WHERE ah.new_status='approved' AND ah.approval_id=(SELECT MAX(ah2.approval_id) FROM approval_history ah2 WHERE ah2.payroll_run_id=ah.payroll_run_id AND ah2.payroll_input_id=ah.payroll_input_id) AND ah.payroll_run_id IN (SELECT MAX(payroll_run_id) FROM payroll_runs GROUP BY pay_period_id)) AS approved_records")[0]
    record_cols=st.columns(2); record_cols[0].metric("Payroll records",f"{record_summary['payroll_records']:,}"); record_cols[1].metric("Approved payroll records",f"{record_summary['approved_records']:,}")
    chart=_frame("SELECT p.pay_period_code,SUM(pr.gross_pay) AS gross_pay,SUM(pr.net_pay) AS net_pay FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) JOIN payroll_results pr USING(payroll_run_id) WHERE r.payroll_run_id=(SELECT MAX(r2.payroll_run_id) FROM payroll_runs r2 WHERE r2.pay_period_id=r.pay_period_id) GROUP BY p.pay_period_id ORDER BY p.period_start")
    c=st.columns(2)
    if not chart.empty: c[0].plotly_chart(px.bar(chart,x="pay_period_code",y=["gross_pay","net_pay"],barmode="group",title="Payroll by period"),use_container_width=True)
    categories=_frame("SELECT rule_code,COUNT(*) AS exceptions FROM exceptions WHERE workflow_status IN ('open','under_review','rejected') GROUP BY rule_code ORDER BY exceptions DESC")
    if not categories.empty: c[1].plotly_chart(px.bar(categories,x="rule_code",y="exceptions",title="Open exceptions by rule"),use_container_width=True)
    st.subheader("Recent payroll runs")
    _show_table(_frame("SELECT p.pay_period_code,r.run_number,r.status,COUNT(pr.payroll_result_id) AS employees,ROUND(SUM(pr.gross_pay),2) AS gross,ROUND(SUM(pr.net_pay),2) AS net FROM payroll_runs r JOIN pay_periods p USING(pay_period_id) LEFT JOIN payroll_results pr USING(payroll_run_id) GROUP BY r.payroll_run_id ORDER BY r.payroll_run_id DESC LIMIT 12"),"dashboard-runs")
