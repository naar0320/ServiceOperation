import streamlit as st
import pandas as pd
from datetime import date, timedelta
from io import BytesIO

from gcp_storage import (
    download_database,
    download_image,
    list_images_for_job,
    list_uploaded_data,
    parse_image_paths,
)
from utils import format_ts_sg, hide_default_sidebar_navigation, require_login, render_role_navigation, today_sg

st.set_page_config(page_title="Review Reports", page_icon="📋", layout="wide")
hide_default_sidebar_navigation()

auth = require_login(min_level_rank=3)
render_role_navigation(auth)

st.title("📋 Review & Download Reports")
st.markdown("---")

DETAIL_COLUMNS = [
    "Job ID", "Job Type", "Job Status", "Severity", "Priority",
    "Maintenance Frequency", "Location", "Create By", "Create at",
    "Assign by", "Time Start", "Time End",
    "Task Description", "Action", "Remark", "Verify by", "Spare Parts Used",
]
TABLE_COLUMNS = [
    "Job ID", "Create at", "Job Status", "Priority", "Severity",
    "Job Type", "Location", "Assign by", "Create By", "Task Description",
]
DATE_FILTER_COLUMNS = ["Create at", "Date"]


def _priority_score(value: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(value or "").strip().lower(), 0)


def _status_score(value: str) -> int:
    return {"pending": 3, "in progress": 2, "completed": 1}.get(str(value or "").strip().lower(), 0)


def _parse_dates(series: pd.Series) -> pd.Series:
    """Parse mixed date/datetime strings to normalized dates."""
    return pd.to_datetime(series.astype(str).str.strip(), errors="coerce").dt.normalize()


def _date_bounds(df: pd.DataFrame, date_col: str) -> tuple[date, date]:
    today = today_sg()
    if date_col not in df.columns or df.empty:
        return today - timedelta(days=30), today
    parsed = _parse_dates(df[date_col]).dropna()
    if parsed.empty:
        return today - timedelta(days=30), today
    return parsed.min().date(), parsed.max().date()


def _apply_date_filter(df: pd.DataFrame, date_col: str, start: date, end: date) -> pd.DataFrame:
    if df.empty or date_col not in df.columns:
        return df
    parsed = _parse_dates(df[date_col])
    mask = parsed.notna() & (parsed >= pd.Timestamp(start)) & (parsed <= pd.Timestamp(end))
    return df[mask]


def _sorted_view(df: pd.DataFrame) -> pd.DataFrame:
    view = df.copy()
    view["__created"] = pd.to_datetime(view.get("Create at"), errors="coerce")
    view["__priority"] = view.get("Priority", pd.Series(dtype=str)).map(_priority_score)
    view["__status"] = view.get("Job Status", pd.Series(dtype=str)).map(_status_score)
    view = view.sort_values(by=["__status", "__priority", "__created"], ascending=[False, False, False], na_position="last")
    cols = [c for c in TABLE_COLUMNS if c in view.columns]
    extra = [c for c in view.columns if c not in cols and not c.startswith("__")]
    return view[cols + extra]


def _render_date_filter(df: pd.DataFrame) -> tuple[pd.DataFrame, str, date, date]:
    """Calendar date-range filter shared across report tabs."""
    available_cols = [c for c in DATE_FILTER_COLUMNS if c in df.columns]
    if not available_cols:
        return df, "", today_sg(), today_sg()

    st.markdown("### 📅 Filter by Date")
    c1, c2, c3 = st.columns([2, 2, 1])

    with c1:
        date_col = st.selectbox(
            "Date field",
            available_cols,
            format_func=lambda x: {
                "Create at": "Created date/time",
                "Date": "Report date",
            }.get(x, x),
        )

    min_d, max_d = _date_bounds(df, date_col)

    with c2:
        preset = st.selectbox(
            "Quick range",
            ["Custom", "Today", "Last 7 days", "Last 30 days", "This month", "All dates"],
            index=5,
        )

    today = today_sg()
    if preset == "Today":
        default_start, default_end = today, today
    elif preset == "Last 7 days":
        default_start, default_end = today - timedelta(days=6), today
    elif preset == "Last 30 days":
        default_start, default_end = today - timedelta(days=29), today
    elif preset == "This month":
        default_start = today.replace(day=1)
        default_end = today
    elif preset == "All dates":
        default_start, default_end = min_d, max_d
    else:
        default_start, default_end = min_d, max_d

    with c3:
        use_filter = st.toggle("Apply filter", value=preset != "All dates")

    cal1, cal2 = st.columns(2)
    with cal1:
        start_date = st.date_input(
            "From",
            value=default_start,
            min_value=min_d,
            max_value=max_d,
            key="filter_date_start",
        )
    with cal2:
        end_date = st.date_input(
            "To",
            value=default_end,
            min_value=min_d,
            max_value=max_d,
            key="filter_date_end",
        )

    if start_date > end_date:
        st.warning("Start date is after end date — swapped automatically.")
        start_date, end_date = end_date, start_date

    filtered = df
    if use_filter:
        filtered = _apply_date_filter(df, date_col, start_date, end_date)
        st.caption(
            f"Showing **{len(filtered)}** of **{len(df)}** reports "
            f"({date_col}: {start_date.strftime('%d %b %Y')} → {end_date.strftime('%d %b %Y')})"
        )
    else:
        st.caption(f"Showing all **{len(df)}** reports (date filter off)")

    st.markdown("---")
    return filtered, date_col, start_date, end_date


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
        filtered_df, active_date_col, range_start, range_end = _render_date_filter(df)
        readable = _sorted_view(filtered_df)

        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "View Job Details",
            "All Reports",
            "Filter by Date",
            "Filter by Status",
            "Search",
            "Cloud Storage",
        ])

        with tab1:
            job_ids = ["— Select Job ID —"] + sorted(filtered_df["Job ID"].dropna().astype(str).unique().tolist())
            selected = st.selectbox("Job ID", job_ids, label_visibility="collapsed")

            if selected != "— Select Job ID —":
                row = filtered_df[filtered_df["Job ID"].astype(str) == selected]
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
                    st.warning("Job not found in current date filter. Widen the date range above.")
            else:
                st.info("Select a Job ID above to view details.")

        with tab2:
            if readable.empty:
                st.info("No reports match the selected date range.")
            else:
                st.dataframe(readable, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download filtered (CSV)",
                    data=readable.to_csv(index=False),
                    file_name=f"task_reports_{range_start}_{range_end}.csv",
                    mime="text/csv",
                )

        with tab3:
            st.markdown("#### Calendar filter")
            st.info(
                f"Use the **From** and **To** calendars at the top of this page. "
                f"Currently filtering **{active_date_col}**."
            )

            if readable.empty:
                st.warning("No reports in this date range.")
            else:
                summary = readable.copy()
                summary["__day"] = _parse_dates(summary[active_date_col]).dt.strftime("%Y-%m-%d")
                daily = (
                    summary.groupby("__day", dropna=True)
                    .size()
                    .reset_index(name="Reports")
                    .sort_values("__day", ascending=False)
                )
                daily.columns = ["Date", "Reports"]
                st.markdown("##### Reports per day")
                st.dataframe(daily, use_container_width=True, hide_index=True)

                st.markdown("##### Reports in range")
                st.dataframe(readable, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download date-filtered (CSV)",
                    data=readable.to_csv(index=False),
                    file_name=f"task_reports_{active_date_col}_{range_start}_{range_end}.csv",
                    mime="text/csv",
                )

        with tab4:
            statuses = (
                ["All"] + sorted(filtered_df["Job Status"].dropna().astype(str).unique().tolist())
                if "Job Status" in filtered_df.columns
                else ["All"]
            )
            chosen = st.selectbox("Status", statuses)
            status_filtered = readable if chosen == "All" else readable[readable["Job Status"].astype(str) == chosen]
            st.caption(f"{len(status_filtered)} report(s)")
            if status_filtered.empty:
                st.info("No reports match status and date filters.")
            else:
                st.dataframe(status_filtered, use_container_width=True, hide_index=True)

        with tab5:
            if readable.empty:
                st.info("No reports to search in current date range.")
            else:
                search_col = st.selectbox("Search field", readable.columns.tolist())
                term = st.text_input("Search term")
                if term:
                    hits = readable[readable[search_col].astype(str).str.contains(term, case=False, na=False)]
                    st.caption(f"{len(hits)} result(s)")
                    st.dataframe(hits, use_container_width=True, hide_index=True)

        with tab6:
            objects = list_uploaded_data()
            if objects:
                obj_df = pd.DataFrame(objects)
                st.dataframe(obj_df, use_container_width=True, hide_index=True)
            else:
                st.info("No files in storage.")

        st.markdown("---")
        st.markdown("#### Summary (date-filtered)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(filtered_df))
        c2.metric("Pending", len(filtered_df[filtered_df["Job Status"] == "Pending"]) if "Job Status" in filtered_df.columns else 0)
        c3.metric("In Progress", len(filtered_df[filtered_df["Job Status"] == "In Progress"]) if "Job Status" in filtered_df.columns else 0)
        c4.metric("Completed", len(filtered_df[filtered_df["Job Status"] == "Completed"]) if "Job Status" in filtered_df.columns else 0)

except Exception as e:
    st.error(f"Error loading reports: {e}")
