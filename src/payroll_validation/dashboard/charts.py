"""Plotly dashboard chart builders."""
import plotly.express as px

def payroll_trend(dataframe):
    return px.line(dataframe, x="period", y="net_pay", title="Net payroll by period")
