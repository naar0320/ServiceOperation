import streamlit as st
import pandas as pd
from io import BytesIO
from utils import require_login, render_role_navigation
from gcp_storage import download_database, list_uploaded_data

st.set_page_config(page_title="Review Reports", page_icon="📋", layout="wide")

# Require Master/Admin level access
auth = require_login(min_level_rank=3)
render_role_navigation(auth)

st.title("📋 Review & Download Reports")
st.markdown("---")

# ======================================
# LOAD TASK DATA
# ======================================
try:
    df = download_database()
    
    if df is None or df.empty:
        st.info("📭 No task reports available")
    else:
        # ======================================
        # TABS FOR FILTERING
        # ======================================
        tab1, tab2, tab3 = st.tabs(["All Reports", "Filter by Status", "Search"])
        
        with tab1:
            st.markdown("### All Task Reports")
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Download full database as CSV
            csv = df.to_csv(index=False)
            st.download_button(
                label="📥 Download All Reports (CSV)",
                data=csv,
                file_name="task_reports_all.csv",
                mime="text/csv"
            )
        
        with tab2:
            st.markdown("### Filter by Job Status")
            
            status_filter = st.selectbox(
                "Select Status",
                ["All"] + df["Job Status"].unique().tolist() if "Job Status" in df.columns else ["All"]
            )
            
            if status_filter == "All":
                filtered_df = df
            else:
                filtered_df = df[df["Job Status"] == status_filter]
            
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
                df.columns.tolist() if df is not None and not df.empty else []
            )
            
            search_term = st.text_input(f"Enter search term for {search_col}")
            
            if search_term:
                if search_col in df.columns:
                    search_df = df[df[search_col].astype(str).str.contains(search_term, case=False, na=False)]
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
            csv = df.to_csv(index=False)
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
                df.to_excel(writer, sheet_name='Task Reports', index=False)
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
