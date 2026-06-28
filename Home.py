import streamlit as st
import pandas as pd

from gcp_storage import download_database
from utils import get_page_icon, hide_default_sidebar_navigation, render_home_auth_controls, render_page_header

st.set_page_config(page_title="Maintenance Dashboard", page_icon=get_page_icon(), layout="wide")
hide_default_sidebar_navigation()
render_home_auth_controls()

render_page_header("Maintenance Dashboard", "Task reports overview")

DISPLAY_COLUMNS = ["Job ID", "Job Type", "Job Status", "Severity", "Priority", "Location", "Create at", "Attend by"]
STATUS_PENDING = "Pending"
STATUS_IN_PROGRESS = "In Progress"
STATUS_COMPLETED = "Completed"


def _count_status(df: pd.DataFrame, status: str) -> int:
    if "Job Status" not in df.columns:
        return 0
    return len(df[df["Job Status"].astype(str) == status])


try:
    df = download_database()

    if df is None or df.empty:
        st.warning("No task reports yet. Log in and create one from Job Entry.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Tasks", len(df))
        with col2:
            st.metric("Pending", _count_status(df, STATUS_PENDING))
        with col3:
            st.metric("In Progress", _count_status(df, STATUS_IN_PROGRESS))
        with col4:
            st.metric("Completed", _count_status(df, STATUS_COMPLETED))

        st.markdown("---")
        st.markdown("## Recent Tasks")

        sort_col = "Create at" if "Create at" in df.columns else df.columns[0]
        recent_df = df.sort_values(by=sort_col, ascending=False).head(10)
        show_cols = [c for c in DISPLAY_COLUMNS if c in recent_df.columns]

        st.dataframe(recent_df[show_cols], use_container_width=True, hide_index=True)
        st.caption(f"Showing latest 10 of {len(df)} total tasks")

except Exception as e:
    st.error(f"Error loading task reports: {e}")
    st.info("Make sure Google Cloud Storage is properly configured.")
