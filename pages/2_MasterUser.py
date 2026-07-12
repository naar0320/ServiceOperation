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
    save_gcs_table,
)
from database_schema import TASK_REPORTS_TABLE
from pdf_report import build_job_report_pdf, image_caption_from_path, prepare_image_for_pdf
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
    "Filter reports and download a single job PDF"
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
_IMAGE_THUMB_W = 108
_IMAGE_PREVIEW_COLS = 4


def _sanitize_job_record(job: dict) -> dict:
    """Clean pandas NaN and internal sort columns before PDF export."""
    clean: dict = {}
    for key, value in job.items():
        if str(key).startswith("__"):
            continue
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        text = str(value).strip()
        if not text or text.lower() == "nan":
            continue
        clean[key] = text if not isinstance(value, (int, float)) else value
    return clean


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
    """Prefer stored DB paths; fall back to GCS listing only if paths are empty."""
    paths = parse_image_paths(job.get("Before Images", ""))
    paths += parse_image_paths(job.get("After Images", ""))
    if paths:
        return sorted(set(paths))
    return list_images_for_job(job_id)


def _short_image_name(path: str) -> str:
    return path.split("/")[-1][:22]


def _preview_thumb_bytes(img_bytes: bytes) -> bytes:
    """Tiny JPEG for on-screen preview — avoids loading full phone photos into the browser."""
    if not img_bytes:
        return b""
    try:
        from PIL import Image

        resample = getattr(Image, "Resampling", Image).LANCZOS
        with Image.open(BytesIO(img_bytes)) as img:
            img = img.convert("RGB")
            img.thumbnail((220, 220), resample)
            out = BytesIO()
            img.save(out, format="JPEG", quality=55, optimize=True)
            return out.getvalue()
    except Exception:
        return prepare_image_for_pdf(img_bytes)


def _render_job_image_previews(image_paths: list[str]) -> None:
    """Small thumbnails — enough to verify photos without full-size display."""
    if not image_paths:
        st.caption("No images for this job.")
        return

    st.markdown(f"**Images** ({len(image_paths)})")
    st.caption("Preview only — PDF uses compressed copies of these photos.")
    per_row = _IMAGE_PREVIEW_COLS
    for row_start in range(0, len(image_paths), per_row):
        row_paths = image_paths[row_start : row_start + per_row]
        cols = st.columns(len(row_paths))
        for col_idx, path in enumerate(row_paths):
            global_idx = row_start + col_idx
            with cols[col_idx]:
                img_bytes = download_image(path)
                kind = image_caption_from_path(path).split("—")[0].strip()
                thumb = _preview_thumb_bytes(img_bytes) if img_bytes else b""
                if thumb:
                    st.image(
                        thumb,
                        width=_IMAGE_THUMB_W,
                        caption=f"#{global_idx + 1} {kind}",
                    )
                else:
                    st.caption(f"#{global_idx + 1} {kind}")
                st.caption(_short_image_name(path))


def _generate_pdf(
    job_data: dict,
    image_paths: list,
    include_images: bool = True,
) -> BytesIO | None:
    try:
        image_items = []
        if include_images:
            for path in image_paths:
                img_bytes = download_image(path)
                if img_bytes:
                    image_items.append((image_caption_from_path(path), img_bytes))
        return build_job_report_pdf(
            _sanitize_job_record(job_data),
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


@st.cache_data(ttl=120, show_spinner="Loading cloud database…")
def _cached_inspect_gcs(remote_path: str) -> dict:
    return inspect_gcs_sqlite(remote_path)


def _render_reports_tab(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.info("No task reports yet. New jobs from **Job Entry** will appear here.")
        return

    filtered = _apply_report_filters(df)
    readable = _sorted_view(filtered)

    if "Job Status" in filtered.columns:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(filtered))
        c2.metric("Pending", len(filtered[filtered["Job Status"] == "Pending"]))
        c3.metric("In Progress", len(filtered[filtered["Job Status"] == "In Progress"]))
        c4.metric("Completed", len(filtered[filtered["Job Status"] == "Completed"]))

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

        for col in DETAIL_COLUMNS:
            if col in job and job[col] not in (None, ""):
                st.markdown(f"**{col}:** {job[col]}")

        all_images = _job_images(selected, job)
        _render_job_image_previews(all_images)

        include_images = st.checkbox(
            "Include images in PDF",
            value=True,
            key=f"pdf_images_{selected}",
        )
        if include_images and len(all_images) >= 10:
            st.caption(
                f"{len(all_images)} photos will be compressed for the PDF "
                "(this may take a short while)."
            )

        pdf_key = f"single_pdf_{selected}_{include_images}_{len(all_images)}"
        if st.session_state.get("single_pdf_key") != pdf_key:
            st.session_state.pop("single_pdf_bytes", None)
            st.session_state["single_pdf_key"] = pdf_key

        if st.button("Generate PDF", type="primary", key=f"gen_pdf_{selected}"):
            with st.spinner("Building PDF…"):
                pdf = _generate_pdf(job, all_images, include_images=include_images)
                if pdf:
                    st.session_state["single_pdf_bytes"] = pdf.getvalue()
                    st.success("PDF ready — download below.")
                else:
                    st.session_state.pop("single_pdf_bytes", None)

        pdf_bytes = st.session_state.get("single_pdf_bytes")
        if pdf_bytes:
            st.download_button(
                f"Download PDF — {selected}",
                data=pdf_bytes,
                file_name=f"job_report_{selected}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )


def _render_cloud_database_tab() -> None:
    st.caption(
        "Live data from Google Cloud Storage. Edit rows below and click **Save to Google Cloud** "
        "to update the database file in the bucket."
    )
    st.warning(
        "Changes are written directly to production data. Double-check rows before saving, "
        "especially user passwords and job records."
    )

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
    default_table = TASK_REPORTS_TABLE if TASK_REPORTS_TABLE in table_names else table_names[0]
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
        st.info("This table is empty. Add rows in the editor below, then save.")

    editor_key = f"cloud_db_editor_{remote_path}_{table_name}"
    edited_df = st.data_editor(
        table_df,
        key=editor_key,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
    )

    save_col, download_col = st.columns([1, 1])
    with save_col:
        if st.button("Save to Google Cloud", type="primary", use_container_width=True):
            normalize = remote_path == REMOTE_DB_PATH and table_name == TASK_REPORTS_TABLE
            ok, message = save_gcs_table(
                remote_path,
                table_name,
                edited_df,
                normalize_task_reports=normalize,
            )
            if ok:
                st.success(message)
                _cached_inspect_gcs.clear()
                st.rerun()
            else:
                st.error(message)

    with download_col:
        st.download_button(
            f"Download {table_name}.csv",
            data=edited_df.to_csv(index=False),
            file_name=f"{table_name}.csv",
            mime="text/csv",
            use_container_width=True,
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
