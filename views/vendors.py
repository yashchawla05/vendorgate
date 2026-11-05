"""Vendor master: approved vendors. Duplicate and ghost-vendor checks (S6) compare against this table."""
import pandas as pd
import streamlit as st

from core import db
from core.models import COUNTRY_NAMES
from ui.theme import page_header

page_header("Vendor master", "Approved vendors. New approvals are added automatically (or by a reviewer).")
rows = db.query("SELECT * FROM vendors ORDER BY vendor_id")
df = pd.DataFrame(rows)
if df.empty:
    st.info("No vendors yet.")
    st.stop()
c1, c2 = st.columns([1, 3])
country = c1.selectbox("Country", ["All"] + list(COUNTRY_NAMES), format_func=lambda c: COUNTRY_NAMES.get(c, c))
query = c2.text_input("Search name, PAN, GSTIN, EIN or account number")
if country != "All":
    df = df[df["country"] == country]
if query.strip():
    q = query.strip().lower()
    mask = df[["legal_name", "trade_name", "pan", "gstin", "ein", "account_number"]].fillna("").apply(
        lambda col: col.str.lower().str.contains(q, regex=False)).any(axis=1)
    df = df[mask]
df["origin"] = df["source_submission_id"].map(lambda s: "seed data" if s == "seed" else f"submission {s}")
st.dataframe(df[["vendor_id", "legal_name", "trade_name", "country", "entity_type", "pan", "gstin", "ein", "company_number",
                 "bank_name", "bank_code", "account_number", "account_holder", "approved_on", "origin"]],
             hide_index=True, width="stretch")
st.caption("All vendors and identifiers are synthetic (PANs in the 'ZZ' series, .example domains).")
