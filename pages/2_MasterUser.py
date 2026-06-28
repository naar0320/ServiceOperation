import zipfile
from datetime import timedelta
from io import BytesIO

import pandas as pd
import streamlit as st

from gcp_storage import (
    REMOTE_DB_PATH,
    REMOTE_REGDATA_PATH,
    count_gcs_images,
    download_database,
    download_image,
    get_gcs_bucket_summary,
    inspect_gcs_sqlite,
    list_images_for_job,
    parse_image_paths,
)
from pdf_report import build_job_report_pdf, image_caption_from_path
from utils import (
    format_ts_sg,
    get_page_icon,
    can_access_cloud_database,
    hide_default_sidebar_navigation,
    render_page_header,
    render_role_navigation,
    require_login,
    today_sg,
)

st.set_page_config(page_title="Review Reports", page_icon=get_page_icon(), layout="wide")
hide_default_sidebar_navigation()

auth = require_login(min_level_rank=2)
render_role_navigation(auth)

user_rank = int(auth.get("rank", 1) or 1)
render_page_header(
    "Review & Download Reports",
    "Filter reports and export PDF / CSV"
    + (" · Cloud DB for Master User only" if not can_access_cloud_database(user_rank) else ""),
)

LIST_COLUMNS = [
    "Job ID", "Create at", "Job Status", "Priority", "Job Type",
    "Location", "Attend by", "Create By",
]
DETAIL_COLUMNS = [
    "Job ID", "Job Type", "Job Status", "Severity", "Priority",
    "Location", "Create By", "Create at", "Date",
    "Attend by", "Time Start", "Time End",
    "Task Description", "Action", "Remark", "Verify by", "Spare Parts Used",
]
DATE_COLUMNS = ["Create at", "Date"]


def _priority_score(value: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(value or "").strip().lower(), 0)


def _status_score(value: str) -> int:
    return {"pending": 3, "in progress": 2, "completed": 1}.get(str(value or "").strip().lower(), 0)


def _parse_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str).str.strip(), errors="coerce").dt.normalize()


def _sorted_view(df: pd.DataFrame) -> pd.DataFrame:
    view = df.copy()
    view["__created"] = pd.to_datetime(view.get("Create at"), errors="coerce")
    view["__priority"] = view.get("Priority", pd.Series(dtype=str)).map(_priority_score)
    view["__status"] = view.get("Job Status", pd.Series(dtype=str)).map(_status_score)
    view = view.sort_values(
        by=["__status", "__priority", "__created"],
        ascending=[False, False, False],
        na_position="last",
    )
    cols = [c for c in LIST_COLUMNS if c in view.columns]
    extra = [c for c in view.columns if c not in cols and not c.startswith("__")]
    return view[cols + extra]


def _apply_report_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Inline filters for the Reports tab."""
    if df.empty:
        return df

    today = today_sg()
    c1, c2, c3 = st.columns([2, 2, 3])

    with c1:
        date_preset = st.selectbox(
            "Date range",
            ["All dates", "Today", "Last 7 days", "Last 30 days", "This month", "Custom"],
            index=0,
        )

    date_col = next((c for c in DATE_COLUMNS if c in df.columns), DATE_COLUMNS[0])
    parsed = _parse_dates(df[date_col])
    min_d = parsed.min().date() if parsed.notna().any() else today - timedelta(days=30)
    max_d = parsed.max().date() if parsed.notna().any() else today

    if date_preset == "Today":
        start_d, end_d = today, today
    elif date_preset == "Last 7 days":
        start_d, end_d = today - timedelta(days=6), today
    elif date_preset == "Last 30 days":
        start_d, end_d = today - timedelta(days=29), today
    elif date_preset == "This month":
        start_d, end_d = today.replace(day=1), today
    elif date_preset == "Custom":
        d1, d2 = st.columns(2)
        with d1:
            start_d = st.date_input("From", value=min_d, min_value=min_d, max_value=max_d, key="rpt_from")
        with d2:
            end_d = st.date_input("To", value=max_d, min_value=min_d, max_value=max_d, key="rpt_to")
        if start_d > end_d:
            start_d, end_d = end_d, start_d
    else:
        start_d, end_d = min_d, max_d

    with c2:
        statuses = ["All"] + sorted(df["Job Status"].dropna().astype(str).unique().tolist()) if "Job Status" in df.columns else ["All"]
        status = st.selectbox("Status", statuses)

    with c3:
        search = st.text_input("Search", placeholder="Job ID, location, description…")

    filtered = df.copy()
    if date_preset != "All dates":
        mask = parsed.notna() & (parsed >= pd.Timestamp(start_d)) & (parsed <= pd.Timestamp(end_d))
        filtered = filtered[mask]

    if status != "All" and "Job Status" in filtered.columns:
        filtered = filtered[filtered["Job Status"].astype(str) == status]

    if search.strip():
        term = search.strip().lower()
        search_cols = [c for c in ["Job ID", "Location", "Task Description", "Create By", "Attend by"] if c in filtered.columns]
        if search_cols:
            mask = pd.Series(False, index=filtered.index)
            for col in search_cols:
                mask |= filtered[col].astype(str).str.lower().str.contains(term, na=False)
            filtered = filtered[mask]

    st.caption(f"**{len(filtered)}** of **{len(df)}** reports shown")
    return filtered


def _job_images(job_id: str, job: dict) -> list[str]:
    paths = list_images_for_job(job_id)
    paths += parse_image_paths(job.get("Before Images", ""))
    paths += parse_image_paths(job.get("After Images", ""))
    return sorted(set(paths))


def _generate_pdf(job_data: dict, image_paths: list, include_images: bool = True) -> BytesIO | None:
    try:
        image_items = []
        if include_images:
            for path in image_paths:
                img_bytes = download_image(path)
                if img_bytes:
                    image_items.append((image_caption_from_path(path), img_bytes))
        return build_job_report_pdf(
            job_data,
            image_items,
            include_images=include_images,
            generated_at=format_ts_sg(),
        )
    except ImportError:
        st.error("reportlab not installed — add it to requirements.txt")
        return None
    except Exception as e:
        st.error(f"PDF error: {e}")
        return None


def _build_pdf_zip(reports_df: pd.DataFrame, include_images: bool) -> BytesIO | None:
    if reports_df.empty:
        return None

    zip_buffer = BytesIO()
    added = 0
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, row in reports_df.iterrows():
            job = row.to_dict()
            job_id = str(job.get("Job ID", f"report_{added + 1}"))
            images = _job_images(job_id, job) if include_images else []
            pdf = _generate_pdf(job, images, include_images=include_images)
            if pdf:
                zf.writestr(f"job_report_{job_id}.pdf", pdf.getvalue())
                added += 1

    if added == 0:
        return None
    zip_buffer.seek(0)
    return zip_buffer


@st.cache_data(ttl=120, show_spinner="Loading cloud database…")
def _cached_inspect_gcs(remote_path: str) -> dict:
    return inspect_gcs_sqlite(remote_path)


def _render_reports_tab(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.info("No task reports yet. New jobs from **Job Entry** will appear here.")
        return

    filtered = _apply_report_filters(df)
    readable = _sorted_view(filtered)

    filter_key = (
        f"{len(filtered)}|{len(readable)}|"
        f"{readable['Job ID'].astype(str).tolist() if 'Job ID' in readable.columns and not readable.empty else ''}"
    )
    if st.session_state.get("report_pdf_filter_key") != filter_key:
        st.session_state.pop("report_pdf_zip", None)
        st.session_state.pop("report_pdf_count", None)
        st.session_state["report_pdf_filter_key"] = filter_key

    if "Job Status" in filtered.columns:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(filtered))
        c2.metric("Pending", len(filtered[filtered["Job Status"] == "Pending"]))
        c3.metric("In Progress", len(filtered[filtered["Job Status"] == "In Progress"]))
        c4.metric("Completed", len(filtered[filtered["Job Status"] == "Completed"]))

    st.markdown("#### Download")
    d1, d2 = st.columns([2, 2])
    with d1:
        include_images = st.checkbox("Include images in PDFs", value=True)
    with d2:
        if not readable.empty:
            st.download_button(
                "Download table (CSV)",
                data=readable.to_csv(index=False),
                file_name=f"task_reports_{today_sg().isoformat()}.csv",
                mime="text/csv",
                use_container_width=True,
            )

    if not readable.empty:
        if st.button(
            f"Prepare all PDFs ({len(filtered)} reports)",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner(f"Building {len(filtered)} PDF(s)…"):
                zip_data = _build_pdf_zip(filtered, include_images)
                if zip_data:
                    st.session_state["report_pdf_zip"] = zip_data.getvalue()
                    st.session_state["report_pdf_count"] = len(filtered)
                else:
                    st.session_state.pop("report_pdf_zip", None)
                    st.error("Could not create PDF files.")

        if st.session_state.get("report_pdf_zip"):
            st.download_button(
                f"Download ZIP — {st.session_state.get('report_pdf_count', 0)} PDF(s) ready",
                data=st.session_state["report_pdf_zip"],
                file_name=f"job_reports_{today_sg().isoformat()}.zip",
                mime="application/zip",
                use_container_width=True,
            )
            st.caption("Click **Prepare all PDFs** again after changing filters.")

    st.markdown("#### Report list")
    if readable.empty:
        st.warning("No reports match your filters. Try **All dates** or clear the search box.")
        return

    display_cols = [c for c in LIST_COLUMNS if c in readable.columns]
    st.dataframe(readable[display_cols], use_container_width=True, hide_index=True)

    st.markdown("#### Job detail")
    job_ids = sorted(filtered["Job ID"].dropna().astype(str).unique().tolist())
    selected = st.selectbox("Select Job ID", job_ids, label_visibility="collapsed")

    if selected:
        row = filtered[filtered["Job ID"].astype(str) == selected]
        if row.empty:
            return
        job = row.iloc[0].to_dict()

        left, right = st.columns([1, 1])
        with left:
            for col in DETAIL_COLUMNS:
                if col in job and job[col] not in (None, ""):
                    st.markdown(f"**{col}:** {job[col]}")

        all_images = _job_images(selected, job)
        with right:
            st.markdown("**Images**")
            if all_images:
                for path in all_images[:6]:
                    img_bytes = download_image(path)
                    if img_bytes:
                        st.image(img_bytes, caption=path.split("/")[-1], use_container_width=True)
                if len(all_images) > 6:
                    st.caption(f"+ {len(all_images) - 6} more image(s) included in PDF")
            else:
                st.caption("No images for this job.")

        pdf = _generate_pdf(job, all_images, include_images=include_images)
        if pdf:
            st.download_button(
                f"Download PDF — {selected}",
                data=pdf,
                file_name=f"job_report_{selected}.pdf",
                mime="application/pdf",
            )


def _render_cloud_database_tab() -> None:
    st.caption("Live data from Google Cloud Storage — task reports, users, and technicians.")

    summary = get_gcs_bucket_summary()
    if summary.get("error"):
        st.error(f"Could not connect to Google Cloud: {summary['error']}")
        return

    head1, head2 = st.columns([3, 1])
    with head1:
        st.markdown(f"**Bucket:** `{summary.get('bucket', '—')}` · **Location:** {summary.get('location', '—')}")
    with head2:
        if st.button("Refresh", use_container_width=True):
            _cached_inspect_gcs.clear()
            st.rerun()

    console_url = summary.get("console_url", "")
    if console_url:
        st.link_button("Open in Google Cloud Console", console_url)

    db_options = {
        "Task reports": REMOTE_DB_PATH,
        "Users & technicians": REMOTE_REGDATA_PATH,
    }
    db_label = st.selectbox("Database", list(db_options.keys()))
    remote_path = db_options[db_label]

    tables = _cached_inspect_gcs(remote_path)
    if not tables:
        st.info("No tables found in this database file.")
        return

    table_names = list(tables.keys())
    default_table = "task_reports" if "task_reports" in table_names else table_names[0]
    table_name = st.selectbox(
        "Table",
        table_names,
        index=table_names.index(default_table) if default_table in table_names else 0,
    )

    info = tables[table_name]
    m1, m2, m3 = st.columns(3)
    m1.metric("Rows", info["row_count"])
    m2.metric("Columns", len(info["columns"]))
    m3.metric("Images in bucket", count_gcs_images())

    table_df = info["dataframe"]
    if table_df.empty:
        st.info("This table is empty.")
    else:
        st.dataframe(table_df, use_container_width=True, hide_index=True)
        st.download_button(
            f"Download {table_name}.csv",
            data=table_df.to_csv(index=False),
            file_name=f"{table_name}.csv",
            mime="text/csv",
        )

    with st.expander("Column schema"):
        st.dataframe(pd.DataFrame(info["columns"]), use_container_width=True, hide_index=True)


try:
    df = download_database()

    if can_access_cloud_database(user_rank):
        tab_reports, tab_database = st.tabs(["Reports", "Cloud Database"])
        with tab_reports:
            _render_reports_tab(df)
        with tab_database:
            _render_cloud_database_tab()
    else:
        _render_reports_tab(df)

except Exception as e:
    st.error(f"Error loading page: {e}")
