"""CAN Log Analyser - Streamlit dashboard.

Views: Overview, Anomaly timeline, ID drill-down, and an Anomaly table with
CSV / Excel download. Reads everything from the PostgreSQL database.

Run:
    streamlit run app/dashboard.py
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import get_engine  # noqa: E402
from src.detect import detect_dropouts  # noqa: E402
from src.report import generate_report  # noqa: E402

st.set_page_config(page_title="CAN Log Analyser", layout="wide")

TYPE_COLORS = {
    "dropout": "#d00000",
    "timing_drift": "#f48c06",
    "unknown_id": "#6a4c93",
    "missing_id": "#277da1",
}


# --------------------------------------------------------------------------- #
# Data access (cached)
# --------------------------------------------------------------------------- #
@st.cache_resource
def engine():
    return get_engine()


@st.cache_data(ttl=300)
def list_logs() -> pd.DataFrame:
    return pd.read_sql(
        "SELECT log_id, filename, vehicle_make, vehicle_model, capture_type, "
        "frame_count, duration_s FROM log_file ORDER BY log_id",
        engine(),
    )


@st.cache_data(ttl=300)
def load_frames(log_id: int) -> pd.DataFrame:
    return pd.read_sql(
        text("SELECT ts AS timestamp, can_id, data, dlc FROM can_frame "
             "WHERE log_id = :l ORDER BY ts"),
        engine(), params={"l": log_id},
    )


@st.cache_data(ttl=300)
def load_anomalies(log_id: int) -> pd.DataFrame:
    return pd.read_sql(
        text("SELECT anomaly_type, can_id, start_ts, end_ts, value, detail "
             "FROM anomaly WHERE log_id = :l ORDER BY start_ts"),
        engine(), params={"l": log_id},
    )


@st.cache_data(ttl=300)
def load_profiles(log_id: int) -> pd.DataFrame:
    return pd.read_sql(
        text("SELECT can_id, frame_count, freq_hz, median_period, period_iqr "
             "FROM id_profile WHERE log_id = :l ORDER BY frame_count DESC"),
        engine(), params={"l": log_id},
    )


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="anomalies")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Sidebar - pick a capture
# --------------------------------------------------------------------------- #
st.title("CAN Log Analyser")
st.caption("Automated fault analysis for automotive CAN bus logs. "
           "Data: CANdid (CC BY 4.0).")

logs = list_logs()
if logs.empty:
    st.warning("No captures loaded. Run `python run_step2.py` first.")
    st.stop()

labels = {
    row.log_id: f"#{row.log_id} - {row.filename} ({row.capture_type})"
    for row in logs.itertuples()
}
log_id = st.sidebar.selectbox("Capture", list(labels), format_func=labels.get)

frames = load_frames(log_id)
anomalies = load_anomalies(log_id)
profiles = load_profiles(log_id)
t0 = float(frames["timestamp"].min())
duration = float(frames["timestamp"].max()) - t0

tab_overview, tab_timeline, tab_drill, tab_table, tab_report = st.tabs(
    ["Overview", "Anomaly timeline", "ID drill-down", "Anomaly table", "AI report"]
)

# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
with tab_overview:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Frames", f"{len(frames):,}")
    c2.metric("Unique IDs", frames["can_id"].nunique())
    c3.metric("Duration", f"{duration:.1f} s")
    c4.metric("Bus rate", f"{len(frames) / duration:,.0f} /s")
    c5.metric("Anomalies", len(anomalies))

    if not anomalies.empty:
        by_type = anomalies["anomaly_type"].value_counts()
        st.subheader("Anomalies by type")
        st.bar_chart(by_type)
    else:
        st.info("No anomalies stored for this capture. "
                "(The clean capture has none - select the injected-faults demo.)")

    st.subheader("Bus traffic over time (frames per 5 s)")
    rel = frames["timestamp"] - t0
    rate = (rel // 5).astype(int).value_counts().sort_index()
    rate.index = rate.index * 5
    st.bar_chart(rate, x_label="time since start (s)", y_label="frames / 5 s")


# --------------------------------------------------------------------------- #
# Anomaly timeline
# --------------------------------------------------------------------------- #
with tab_timeline:
    st.subheader("When and where anomalies occur")
    if anomalies.empty:
        st.info("No anomalies to plot for this capture.")
    else:
        a = anomalies.copy()
        a["t"] = a["start_ts"] - t0
        ids = sorted(a["can_id"].dropna().unique())
        ypos = {cid: i for i, cid in enumerate(ids)}

        fig, ax = plt.subplots(figsize=(11, max(2.5, 0.4 * len(ids) + 1)))
        for atype, grp in a.groupby("anomaly_type"):
            ax.scatter(grp["t"], [ypos[c] for c in grp["can_id"]],
                       s=60, color=TYPE_COLORS.get(atype, "#555"),
                       label=atype, alpha=0.8, edgecolors="white")
        ax.set_yticks(range(len(ids)))
        ax.set_yticklabels(ids)
        ax.set_xlabel("time since capture start (s)")
        ax.set_ylabel("CAN ID")
        ax.set_title("Anomaly timeline")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(axis="x", alpha=0.3)
        fig.tight_layout()
        st.pyplot(fig)


# --------------------------------------------------------------------------- #
# ID drill-down
# --------------------------------------------------------------------------- #
with tab_drill:
    st.subheader("Inspect one CAN ID's timing")
    pick = st.selectbox("CAN ID", profiles["can_id"].tolist())
    prow = profiles[profiles["can_id"] == pick].iloc[0]

    m1, m2, m3 = st.columns(3)
    m1.metric("Frames", f"{int(prow['frame_count']):,}")
    m2.metric("Rate", f"{prow['freq_hz']:.1f} Hz")
    m3.metric("Median period", f"{prow['median_period'] * 1000:.1f} ms")

    g = frames[frames["can_id"] == pick].sort_values("timestamp")
    ts = g["timestamp"].to_numpy()
    if len(ts) > 2:
        rel = ts[1:] - t0
        gaps_ms = (ts[1:] - ts[:-1]) * 1000
        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(rel, gaps_ms, ".", ms=4, color="#2a6f97")
        # mark this ID's stored anomalies
        for row in anomalies[anomalies["can_id"] == pick].itertuples():
            ax.axvspan(row.start_ts - t0, row.end_ts - t0, color="#d00000", alpha=0.25)
        ax.set_xlabel("time since start (s)")
        ax.set_ylabel("gap before frame (ms)")
        ax.set_title(f"ID {pick} - inter-frame gaps (red = flagged dropout)")
        fig.tight_layout()
        st.pyplot(fig)


# --------------------------------------------------------------------------- #
# Anomaly table + downloads
# --------------------------------------------------------------------------- #
with tab_table:
    st.subheader("Detected anomalies")
    if anomalies.empty:
        st.info("No anomalies for this capture.")
    else:
        show = anomalies.copy()
        show["start_s"] = (show["start_ts"] - t0).round(3)
        show = show[["anomaly_type", "can_id", "start_s", "value", "detail"]]
        st.dataframe(show, use_container_width=True, hide_index=True)

        c1, c2 = st.columns(2)
        c1.download_button(
            "⬇ Download CSV", show.to_csv(index=False).encode(),
            file_name=f"anomalies_log{log_id}.csv", mime="text/csv",
        )
        c2.download_button(
            "⬇ Download Excel", to_excel_bytes(show),
            file_name=f"anomalies_log{log_id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# --------------------------------------------------------------------------- #
# AI report
# --------------------------------------------------------------------------- #
with tab_report:
    st.subheader("Generate a test report")
    st.caption("Uses a local LLM (Ollama) if it is running, otherwise a built-in "
               "template. Either way the report uses only the computed numbers "
               "and is a draft to review before use.")
    if st.button("Generate report", type="primary"):
        with st.spinner("Writing report..."):
            report_md, source = generate_report(engine(), log_id)
        if source == "template-fallback":
            st.info("Ollama not detected - used the built-in template. Install "
                    "Ollama and run `ollama pull llama3.2` for LLM-written prose.")
        else:
            st.success(f"Written by local model ({source}).")
        st.markdown(report_md)
        st.download_button(
            "⬇ Download report (Markdown)", report_md.encode(),
            file_name=f"report_log{log_id}.md", mime="text/markdown",
        )
