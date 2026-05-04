import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from utils import hide_default_sidebar_navigation, require_login, render_role_navigation, format_ts_sg
from gcp_storage import download_database, list_uploaded_data, download_image, list_images_for_job

st.set_page_config(page_title="Review Reports", page_icon="📋", layout="wide")
hide_default_sidebar_navigation()

# Require Master/Admin level access
auth = require_login(min_level_rank=3)
render_role_navigation(auth)

st.title("📋 Review & Download Reports")
st.markdown("---")


def _generate_pdf_report(job_data: dict, images_list: list) -> BytesIO:
    """Generate PDF report with job details and images"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage, PageBreak
        from reportlab.lib import colors
        
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1f77b4'),
            spaceAfter=12,
            alignment=1
        )
        elements.append(Paragraph("📋 Job Report", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Job Details Section
        details_data = []
        for key, value in job_data.items():
            if not str(key).startswith('__'):
                details_data.append([str(key), str(value)[:100]])
        
        if details_data:
            details_table = Table(details_data, colWidths=[2*inch, 3.5*inch])
            details_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            elements.append(details_table)
            elements.append(Spacer(1, 0.3*inch))
        
        # Images Section
        if images_list:
            elements.append(Paragraph("📸 Uploaded Images", styles['Heading2']))
            elements.append(Spacer(1, 0.1*inch))
            
            for img_path in images_list:
                try:
                    img_bytes = download_image(img_path)
                    if img_bytes:
                        img_buffer = BytesIO(img_bytes)
                        rl_image = RLImage(img_buffer, width=3*inch, height=2*inch)
                        elements.append(rl_image)
                        elements.append(Paragraph(f"<font size=8>{img_path.split('/')[-1]}</font>", styles['Normal']))
                        elements.append(Spacer(1, 0.2*inch))
                except Exception:
                    pass
        
        # Footer
        elements.append(Spacer(1, 0.3*inch))
        footer_text = f"Generated on {format_ts_sg()} | Ammar Builders Maintenance System"
        elements.append(Paragraph(f"<font size=8 color='gray'>{footer_text}</font>", styles['Normal']))
        
        doc.build(elements)
        pdf_buffer.seek(0)
        return pdf_buffer
        
    except ImportError:
        st.error("❌ reportlab not installed. Please install: pip install reportlab")
        return None
    except Exception as e:
        st.error(f"❌ PDF generation error: {e}")
        return None


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
        # MAIN TABS
        # ======================================
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📄 View Job Details", 
            "📋 All Reports", 
            "🔍 Filter by Status", 
            "🔎 Search", 
            "☁️ Cloud Storage"
        ])
        
        # ======================================
        # TAB 1: VIEW JOB DETAILS
        # ======================================
        with tab1:
            st.markdown("### 📄 View Complete Job Report with Images")
            
            job_ids = ["---Select a Job ID---"] + sorted([str(jid) for jid in df["Job ID"].dropna().unique().tolist()])
            selected_job_id = st.selectbox("Select Job ID to View", job_ids, key="job_selector", label_visibility="collapsed")
            
            if selected_job_id != "---Select a Job ID---":
                job_row = df[df["Job ID"] == selected_job_id]
                
                if not job_row.empty:
                    job_data = job_row.iloc[0].to_dict()
                    images_list = list_images_for_job(selected_job_id)
                    
                    # Header
                    st.markdown(f"## 📋 Job Report: **{selected_job_id}**")
                    st.markdown("---")
                    
                    # Create columns for job details
                    st.markdown("### Job Information")
                    
                    # Organize fields into groups
                    detail_cols = st.columns(3)
                    col_idx = 0
                    
                    for key, value in job_data.items():
                        if not str(key).startswith('__'):
                            with detail_cols[col_idx % 3]:
                                with st.container(border=True):
                                    st.markdown(f"**{key}**")
                                    st.write(str(value)[:300] if len(str(value)) > 300 else value)
                            col_idx += 1
                    
                    st.markdown("---")
                    
                    # Images Section
                    st.markdown("### 📸 Uploaded Images")
                    
                    if images_list:
                        st.success(f"✅ {len(images_list)} image(s) found for this job")
                        
                        img_cols = st.columns(2)
                        for idx, img_path in enumerate(images_list):
                            try:
                                img_bytes = download_image(img_path)
                                if img_bytes:
                                    with img_cols[idx % 2]:
                                        with st.container(border=True):
                                            st.image(img_bytes, use_container_width=True, caption=img_path.split('/')[-1])
                                            st.download_button(
                                                label="📥 Download Image",
                                                data=img_bytes,
                                                file_name=img_path.split('/')[-1],
                                                mime="image/jpeg",
                                                key=f"img_dl_{idx}",
                                                use_container_width=True
                                            )
                            except Exception as e:
                                st.warning(f"❌ Could not load: {img_path}")
                    else:
                        st.info("📭 No images uploaded for this job")
                    
                    st.markdown("---")
                    
                    # PDF Export
                    st.markdown("### 💾 Export Report")
                    pdf_buffer = _generate_pdf_report(job_data, images_list)
                    if pdf_buffer:
                        col1, col2, col3 = st.columns([1, 1, 2])
                        with col1:
                            st.download_button(
                                label="📥 Download as PDF",
                                data=pdf_buffer,
                                file_name=f"job_report_{selected_job_id}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
            else:
                st.info("👆 Please select a Job ID from the dropdown above to view details")
        
        # ======================================
        # TAB 2: ALL REPORTS
        # ======================================
        with tab2:
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
        
        with tab3:
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
        
        with tab4:
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
        # TAB 5: CLOUD STORAGE
        # ======================================
        with tab5:
            st.markdown("### ☁️ Uploaded Data (All Files in GCS)")
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
        
        # ======================================
        # STATISTICS SUMMARY (BELOW TABS)
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

except Exception as e:
    st.error(f"❌ Error loading reports: {e}")
    st.info("Make sure Google Cloud Storage is properly configured")
