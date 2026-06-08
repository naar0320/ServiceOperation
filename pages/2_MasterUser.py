import streamlit as st
import pandas as pd
from io import BytesIO

from gcp_storage import (
    download_database,
    download_image,
    list_images_for_job,
    list_uploaded_data,
    parse_image_paths,
)
from utils import format_ts_sg, hide_default_sidebar_navigation, require_login, render_role_navigation

st.set_page_config(page_title="Review Reports", page_icon="📋", layout="wide")
hide_default_sidebar_navigation()

auth = require_login(min_level_rank=3)
render_role_navigation(auth)

st.title("📋 Review & Download Reports")
st.markdown("---")

DETAIL_COLUMNS = [
    "Job ID", "Job Type", "Job Status", "Severity", "Priority",
    "Maintenance Frequency", "Shift", "Location", "Create By", "Create at",
    "Assign by", "Date Start", "Time Start", "Date End", "Time End",
    "Machine ID", "Machine/Equipment", "Task Description", "Action",
    "Remark", "Verify by", "Spare Parts Used",
]
TABLE_COLUMNS = [
    "Job ID", "Create at", "Job Status", "Priority", "Severity",
    "Job Type", "Location", "Assign by", "Create By", "Machine ID", "Task Description",
]


def _priority_score(value: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(value or "").strip().lower(), 0)


def _status_score(value: str) -> int:
    return {"pending": 3, "in progress": 2, "completed": 1}.get(str(value or "").strip().lower(), 0)


def _sorted_view(df: pd.DataFrame) -> pd.DataFrame:
    view = df.copy()
    view["__created"] = pd.to_datetime(view.get("Create at"), errors="coerce")
    view["__priority"] = view.get("Priority", pd.Series(dtype=str)).map(_priority_score)
    view["__status"] = view.get("Job Status", pd.Series(dtype=str)).map(_status_score)
    view = view.sort_values(by=["__status", "__priority", "__created"], ascending=[False, False, False], na_position="last")
    cols = [c for c in TABLE_COLUMNS if c in view.columns]
    extra = [c for c in view.columns if c not in cols and not c.startswith("__")]
    return view[cols + extra]


def _generate_pdf(job_data: dict, image_paths: list) -> BytesIO | None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Image as RLImage
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=0.5 * inch, rightMargin=0.5 * inch)
        styles = getSampleStyleSheet()
        elements = []

        title = ParagraphStyle("title", parent=styles["Heading1"], fontSize=20, alignment=1, spaceAfter=12)
        elements.append(Paragraph("Job Report — Ammar Builders Maintenance", title))
        elements.append(Spacer(1, 0.2 * inch))

        rows = [[str(k), str(v)[:200]] for k, v in job_data.items() if not str(k).startswith("__")]
        table = Table(rows, colWidths=[2 * inch, 4 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(table)

        if image_paths:
            elements.append(Spacer(1, 0.3 * inch))
            elements.append(Paragraph("Images", styles["Heading2"]))
            for path in image_paths[:8]:
                img_bytes = download_image(path)
                if img_bytes:
                    elements.append(RLImage(BytesIO(img_bytes), width=3 * inch, height=2 * inch))
                    elements.append(Spacer(1, 0.1 * inch))

        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph(f"<font size=8>Generated {format_ts_sg()}</font>", styles["Normal"]))
        doc.build(elements)
        buffer.seek(0)
        return buffer
    except ImportError:
        st.error("reportlab not installed")
        return None
    except Exception as e:
        st.error(f"PDF error: {e}")
        return None


try:
    df = download_database()

    if df is None or df.empty:
        st.info("No task reports available.")
    else:
        readable = _sorted_view(df)

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "View Job Details", "All Reports", "Filter by Status", "Search", "Cloud Storage"
        ])

        with tab1:
            job_ids = ["— Select Job ID —"] + sorted(df["Job ID"].dropna().astype(str).unique().tolist())
            selected = st.selectbox("Job ID", job_ids, label_visibility="collapsed")

            if selected != "— Select Job ID —":
                row = df[df["Job ID"].astype(str) == selected]
                if not row.empty:
                    job = row.iloc[0].to_dict()
                    st.markdown(f"## Job Report: **{selected}**")
                    st.markdown("---")

                    for col_name in DETAIL_COLUMNS:
                        if col_name in job and job[col_name] not in (None, ""):
                            st.markdown(f"**{col_name}:** {job[col_name]}")

                    image_paths = list_images_for_job(selected)
                    stored_before = parse_image_paths(job.get("Before Images", ""))
                    stored_after = parse_image_paths(job.get("After Images", ""))
                    all_images = sorted(set(image_paths + stored_before + stored_after))

                    st.markdown("---")
                    st.markdown("### Images")
                    if all_images:
                        cols = st.columns(2)
                        for idx, path in enumerate(all_images):
                            img_bytes = download_image(path)
                            if img_bytes:
                                with cols[idx % 2]:
                                    st.image(img_bytes, caption=path.split("/")[-1], use_container_width=True)
                    else:
                        st.info("No images for this job.")

                    pdf = _generate_pdf(job, all_images)
                    if pdf:
                        st.download_button(
                            "Download PDF",
                            data=pdf,
                            file_name=f"job_report_{selected}.pdf",
                            mime="application/pdf",
                        )
            else:
                st.info("Select a Job ID above to view details.")

        with tab2:
            st.dataframe(readable, use_container_width=True, hide_index=True)
            st.download_button(
                "Download All (CSV)",
                data=readable.to_csv(index=False),
                file_name="task_reports_all.csv",
                mime="text/csv",
            )

        with tab3:
            statuses = ["All"] + sorted(df["Job Status"].dropna().astype(str).unique().tolist()) if "Job Status" in df.columns else ["All"]
            chosen = st.selectbox("Status", statuses)
            filtered = readable if chosen == "All" else readable[readable["Job Status"].astype(str) == chosen]
            st.caption(f"{len(filtered)} report(s)")
            st.dataframe(filtered, use_container_width=True, hide_index=True)

        with tab4:
            search_col = st.selectbox("Search field", readable.columns.tolist())
            term = st.text_input("Search term")
            if term:
                hits = readable[readable[search_col].astype(str).str.contains(term, case=False, na=False)]
                st.caption(f"{len(hits)} result(s)")
                st.dataframe(hits, use_container_width=True, hide_index=True)

        with tab5:
            objects = list_uploaded_data()
            if objects:
                obj_df = pd.DataFrame(objects)
                st.dataframe(obj_df, use_container_width=True, hide_index=True)
            else:
                st.info("No files in storage.")

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(df))
        c2.metric("Pending", len(df[df["Job Status"] == "Pending"]) if "Job Status" in df.columns else 0)
        c3.metric("In Progress", len(df[df["Job Status"] == "In Progress"]) if "Job Status" in df.columns else 0)
        c4.metric("Completed", len(df[df["Job Status"] == "Completed"]) if "Job Status" in df.columns else 0)

except Exception as e:
    st.error(f"Error loading reports: {e}")
