import streamlit as st
import pandas as pd
from utils import hide_default_sidebar_navigation, render_home_auth_controls
from gcp_storage import download_database

st.set_page_config(page_title="Maintenance Dashboard", page_icon="??", layout="wide")
hide_default_sidebar_navigation()

# Home page is accessible without login.
# Login here only unlocks edit pages.
render_home_auth_controls()

st.title("🛠️Maintenance Dashboard")
st.markdown("---")

# ======================================
# Load Task Reports from Google Cloud
# ======================================
try:
    df = download_database()
    
    if df is None or df.empty:
        st.warning("⚠️No task reports yet")
    else:
        # Get task statistics
        pending_count = 0
        in_progress_count = 0
        completed_count = 0
        
        if "Job Status" in df.columns:
            pending_count = len(df[df["Job Status"] == "Pending"])
            in_progress_count = len(df[df["Job Status"] == "In Progress"])
            completed_count = len(df[df["Job Status"] == "Completed"])
        
        # Display statistics in 3 columns
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("📌 Pending Tasks", pending_count)
        
        with col2:
            st.metric("👷‍♂️ In Progress", in_progress_count)
        
        with col3:
            st.metric("🚩Completed", completed_count)
        
        st.markdown("---")
        
        # Show recent tasks
        st.markdown("## ⌚Recent Tasks")
        
        if len(df) > 0:
            # Get latest 10 tasks
            recent_df = df.sort_values(
                by="Create at" if "Create at" in df.columns else df.columns[0],
                ascending=False
            ).head(10)
            
            # Select columns to display
            display_cols = [col for col in ["Job ID", "Job Type", "Job Status", "Severity", "Create at"] 
                           if col in recent_df.columns]
            
            st.dataframe(
                recent_df[display_cols],
                use_container_width=True,
                hide_index=True
            )
            
            st.markdown(f"Showing latest 10 of {len(df)} total tasks")

except Exception as e:
    st.error(f"? Error loading task reports: {e}")
    st.info("Make sure Google Cloud Storage is properly configured")
