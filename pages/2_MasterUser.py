import streamlit as st
import pandas as pd
from io import BytesIO
from utils import hide_default_sidebar_navigation, require_login, render_role_navigation
from gcp_storage import download_database, list_uploaded_data

st.set_page_config(page_title="Review Reports", page_icon="📋", layout="wide")
hide_default_sidebar_navigation()

# Require Master/Admin level access
auth = require_login(min_level_rank=3)
render_role_navigation(auth)

st.title("📋 Review & Download Reports")
st.markdown("---")


def _priority_score(value: str) -> int:
    text = str(value or "").strip().lower()
    mapping = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    return mapping.get(text, 0)


def _status_score(value: str) -> int:
    text = str(value or "").strip().lower()
    mapping = {"pending": 3, "in progress": 2, "completed": 1}
    return mapping.get(text, 0)


def _sorted_task_view(df: pd.DataFrame) -> pd.DataFrame:
    """Return a readable task view for Master User."""
    view_df = df.copy()
    if "Create at" in view_df.columns:
        view_df["__create_at_sort"] = pd.to_datetime(view_df["Create at"], errors="coerce")
    else:
        view_df["__create_at_sort"] = pd.NaT

    if "Priority" in view_df.columns:
        view_df["__priority_sort"] = view_df["Priority"].map(_priority_score)
    else:
        view_df["__priority_sort"] = 0

    if "Job Status" in view_df.columns:
        view_df["__status_sort"] = view_df["Job Status"].map(_status_score)
    else:
        view_df["__status_sort"] = 0

    view_df = view_df.sort_values(
        by=["__status_sort", "__priority_sort", "__create_at_sort"],
        ascending=[False, False, False],
        na_position="last",
    )

    key_columns = [
        "Job ID",
        "Create at",
        "Job Status",
        "Priority",
        "Severity",
        "Job Type",
        "Location",
        "Assign by",
        "Create By",
        "Machine ID",
        "Task Description",
    ]
    ordered_columns = [c for c in key_columns if c in view_df.columns]
    remaining_columns = [c for c in view_df.columns if c not in ordered_columns and not c.startswith("__")]
    return view_df[ordered_columns + remaining_columns]

# ======================================
# LOAD TASK DATA
# ======================================
try:
    df = download_database()
    
    if df is None or df.empty:
        st.info("📭 No task reports available")
    else:
        readable_df = _sorted_task_view(df)

        # ======================================
        # TABS FOR FILTERING
        # ======================================
        tab1, tab2, tab3 = st.tabs(["All Reports", "Filter by Status", "Search"])
        
        with tab1:
            st.markdown("### All Task Reports (Readable Order)")
            st.caption("Sorted by status, priority, then latest created time.")
            st.dataframe(readable_df, use_container_width=True, hide_index=True)
            
            # Download full database as CSV
            csv = readable_df.to_csv(index=False)
            st.download_button(
                label="📥 Download All Reports (CSV)",
                data=csv,
                file_name="task_reports_all.csv",
                mime="text/csv"
            )
        
        with tab2:
            st.markdown("### Filter by Job Status")
            
            status_options = ["All"]
            if "Job Status" in readable_df.columns:
                unique_statuses = [s for s in readable_df["Job Status"].dropna().astype(str).unique().tolist() if s]
                status_options += sorted(unique_statuses)

            status_filter = st.selectbox(
                "Select Status",
                status_options
            )
            
            if status_filter == "All":
                filtered_df = readable_df
            else:
                filtered_df = readable_df[readable_df["Job Status"] == status_filter]
            
            st.markdown(f"**Found {len(filtered_df)} report(s)**")
            st.dataframe(filtered_df, use_container_width=True, hide_index=True)
            
            # Download filtered data
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label=f"📥 Download {status_filter} Reports (CSV)",
                data=csv,
                file_name=f"task_reports_{status_filter}.csv",
                mime="text/csv"
            )
        
        with tab3:
            st.markdown("### Search Reports")
            
            search_col = st.selectbox(
                "Search by field",
                readable_df.columns.tolist() if readable_df is not None and not readable_df.empty else []
            )
            
            search_term = st.text_input(f"Enter search term for {search_col}")
            
            if search_term:
                if search_col in readable_df.columns:
                    search_df = readable_df[readable_df[search_col].astype(str).str.contains(search_term, case=False, na=False)]
                    st.markdown(f"**Found {len(search_df)} report(s)**")
                    st.dataframe(search_df, use_container_width=True, hide_index=True)
                    
                    # Download search results
                    csv = search_df.to_csv(index=False)
                    st.download_button(
                        label=f"📥 Download Search Results (CSV)",
                        data=csv,
                        file_name=f"task_reports_search_{search_term}.csv",
                        mime="text/csv"
                    )
                else:
                    st.warning(f"Column '{search_col}' not found")
        
        # ======================================
        # STATISTICS SUMMARY
        # ======================================
        st.markdown("---")
        st.markdown("### 📊 Summary Statistics")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Reports", len(df))
        
        with col2:
            if "Job Status" in df.columns:
                pending = len(df[df["Job Status"] == "Pending"])
                st.metric("Pending", pending)
            else:
                st.metric("Pending", "-")
        
        with col3:
            if "Job Status" in df.columns:
                in_progress = len(df[df["Job Status"] == "In Progress"])
                st.metric("In Progress", in_progress)
            else:
                st.metric("In Progress", "-")
        
        with col4:
            if "Job Status" in df.columns:
                completed = len(df[df["Job Status"] == "Completed"])
                st.metric("Completed", completed)
            else:
                st.metric("Completed", "-")
        
        # ======================================
        # EXPORT DATABASE
        # ======================================
        st.markdown("---")
        st.markdown("### 💾 Export Options")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Export as CSV
            csv = readable_df.to_csv(index=False)
            st.download_button(
                label="📥 Export as CSV",
                data=csv,
                file_name="task_reports_export.csv",
                mime="text/csv"
            )
        
        with col2:
            # Export as Excel
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                readable_df.to_excel(writer, sheet_name='Task Reports', index=False)
            excel_buffer.seek(0)
            
            st.download_button(
                label="📥 Export as Excel",
                data=excel_buffer.getvalue(),
                file_name="task_reports_export.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        # ======================================
        # READ ALL UPLOADED DATA
        # ======================================
        st.markdown("---")
        st.markdown("### ☁️ Uploaded Data (All Files)")
        uploaded_objects = list_uploaded_data()
        if not uploaded_objects:
            st.info("No uploaded files found in storage.")
        else:
            uploaded_df = pd.DataFrame(uploaded_objects)
            if "Updated" in uploaded_df.columns:
                uploaded_df["__updated_sort"] = pd.to_datetime(uploaded_df["Updated"], errors="coerce")
                uploaded_df = uploaded_df.sort_values(by="__updated_sort", ascending=False, na_position="last")
                uploaded_df = uploaded_df.drop(columns=["__updated_sort"])
            st.dataframe(uploaded_df, use_container_width=True, hide_index=True)
            upload_csv = uploaded_df.to_csv(index=False)
            st.download_button(
                label="📥 Download Uploaded Data List (CSV)",
                data=upload_csv,
                file_name="uploaded_data_list.csv",
                mime="text/csv"
            )

except Exception as e:
    st.error(f"❌ Error loading reports: {e}")
    st.info("Make sure Google Cloud Storage is properly configured")
