import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path

from database_schema import (
    JOB_TYPES,
    SEVERITY_OPTIONS,
    PRIORITY_OPTIONS,
    FREQUENCY_OPTIONS,
    SHIFT_OPTIONS,
    JOB_STATUS_OPTIONS,
    validate_task_report,
)
from gcp_storage import (
    generate_job_id,
    get_technician_list,
    get_user_list,
    save_task_report,
    upload_image,
)
from utils import (
    format_ts_sg,
    hide_default_sidebar_navigation,
    now_sg,
    render_role_navigation,
    require_login,
    today_sg,
)

st.set_page_config(page_title="Job Entry", page_icon="📝", layout="wide")
hide_default_sidebar_navigation()

auth = require_login(min_level_rank=2)
render_role_navigation(auth)

st.title("📝 Job Task Entry Form")
st.markdown("Create a new maintenance task report")
st.markdown("---")


def _current_user_name() -> str:
    return str(auth.get("name") or auth.get("user_id") or "System").strip()


def _upload_images(uploaded_files, job_id: str, image_type: str) -> list[str]:
    if not uploaded_files:
        return []
    paths = []
    for i, uploaded_file in enumerate(uploaded_files, start=1):
        try:
            ext = Path(uploaded_file.name).suffix.lower() or ".jpeg"
            image_bytes = uploaded_file.getbuffer().tobytes()
            path = upload_image(image_bytes, job_id, image_type, i, ext)
            if path:
                paths.append(path)
        except Exception:
            st.error(f"Failed to upload: {uploaded_file.name}")
    return paths


if "spare_parts" not in st.session_state:
    st.session_state.spare_parts = []

assign_options = list(dict.fromkeys(get_technician_list() + get_user_list())) or ["No assignees loaded"]

with st.form("job_entry_form"):
    st.markdown("#### Job Classification")
    c1, c2, c3 = st.columns(3)
    with c1:
        job_type = st.selectbox("Job Type *", [""] + JOB_TYPES)
    with c2:
        severity = st.selectbox("Severity *", [""] + SEVERITY_OPTIONS)
    with c3:
        priority = st.selectbox("Priority *", [""] + PRIORITY_OPTIONS)

    c1, c2, c3 = st.columns(3)
    with c1:
        frequency = st.selectbox("Maintenance Frequency *", [""] + FREQUENCY_OPTIONS)
    with c2:
        shift = st.selectbox("Shift *", [""] + SHIFT_OPTIONS)
    with c3:
        location = st.text_input("Location *", placeholder="e.g. Zone 1")

    job_id = generate_job_id(job_type if job_type else "Maintenance")
    st.caption(f"**Job ID:** `{job_id}`")

    st.markdown("#### Schedule & Assignment")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        date_start = st.date_input("Date Start *", value=today_sg())
    with c2:
        time_start = st.time_input("Time Start *", value=datetime.now().time())
    with c3:
        date_end = st.date_input("Date End", value=today_sg())
    with c4:
        time_end = st.time_input("Time End", value=datetime.now().time())

    c1, c2 = st.columns(2)
    with c1:
        assign_by = st.selectbox("Assign by *", [""] + assign_options)
    with c2:
        job_status = st.selectbox("Job Status *", [""] + JOB_STATUS_OPTIONS)

    st.markdown("#### Machine & Task Details")
    c1, c2 = st.columns(2)
    with c1:
        machine_id = st.text_input("Machine ID", placeholder="NA")
    with c2:
        machine_equipment = st.text_input("Machine/Equipment", placeholder="NA")

    task_description = st.text_area("Task Description *", height=100, placeholder="Describe the task")
    action = st.text_area("Action", height=80, placeholder="Action taken or planned")
    remark = st.text_area("Remark", height=60, placeholder="Additional notes")
    verify_by = st.text_input("Verify by", placeholder="Verifier name")

    st.markdown("#### Images")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Before (min 4 for Completed submit)**")
        before_files = st.file_uploader(
            "Before images",
            type=["jpg", "jpeg", "png", "gif", "webp"],
            accept_multiple_files=True,
            key="before_images",
        )
        st.caption(f"Selected: {len(before_files) if before_files else 0}")
    with c2:
        st.markdown("**After (min 4 for Completed submit)**")
        after_files = st.file_uploader(
            "After images",
            type=["jpg", "jpeg", "png", "gif", "webp"],
            accept_multiple_files=True,
            key="after_images",
        )
        st.caption(f"Selected: {len(after_files) if after_files else 0}")

    st.markdown("#### Spare Parts Used")
    spare_text = st.text_input("Spare Parts (comma-separated or NA)", placeholder="e.g. hinge x2, bolt x4")

    submitted = st.form_submit_button("Save Report", use_container_width=True, type="primary")

if submitted:
    spare_parts_value = spare_text.strip()
    if st.session_state.spare_parts:
        parts_str = "; ".join(
            f"{p['item_name']} x{p['quantity']}" for p in st.session_state.spare_parts
        )
        spare_parts_value = parts_str if not spare_parts_value else f"{spare_parts_value}; {parts_str}"

    record = {
        "Job Type": job_type,
        "Create By": _current_user_name(),
        "Create at": format_ts_sg(now_sg()),
        "Date": today_sg().isoformat(),
        "Job ID": job_id,
        "Severity": severity,
        "Priority": priority,
        "Maintenance Frequency": frequency,
        "Shift": shift,
        "Location": location.strip(),
        "Job Status": job_status,
        "Assign by": assign_by,
        "Date Start": date_start.isoformat(),
        "Time Start": time_start.strftime("%H:%M:%S"),
        "Machine ID": machine_id.strip() or "NA",
        "Date End": date_end.isoformat() if date_end else "",
        "Time End": time_end.strftime("%H:%M:%S") if time_end else "",
        "Machine/Equipment": machine_equipment.strip() or "NA",
        "Task Description": task_description.strip(),
        "Action": action.strip() or "NA",
        "Remark": remark.strip() or "NA",
        "Verify by": verify_by.strip() or "NA",
        "Spare Parts Used": spare_parts_value or "NA",
        "Before Images": "",
        "After Images": "",
    }

    require_images = job_status == "Completed"
    is_valid, errors = validate_task_report(record, require_images=False)

    if require_images:
        before_count = len(before_files) if before_files else 0
        after_count = len(after_files) if after_files else 0
        if before_count < 4:
            errors.append(f"Before images: {before_count}/4 required for Completed status")
        if after_count < 4:
            errors.append(f"After images: {after_count}/4 required for Completed status")

    if errors:
        st.error("Please fix the following:\n" + "\n".join(f"• {e}" for e in errors))
    else:
        with st.spinner("Uploading images..."):
            if before_files:
                record["Before Images"] = ",".join(_upload_images(before_files, job_id, "before"))
            if after_files:
                record["After Images"] = ",".join(_upload_images(after_files, job_id, "after"))

        with st.spinner("Saving to cloud..."):
            if save_task_report(record):
                st.success(f"Report saved successfully — Job ID: **{job_id}**")
                st.balloons()
                st.session_state.spare_parts = []
            else:
                st.error("Failed to save report. Please try again.")

st.markdown("---")
st.markdown("**Quick-add spare parts**")
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    spare_item = st.text_input("Item name", key="spare_item_out")
with c2:
    spare_qty = st.number_input("Qty", min_value=1, value=1, key="spare_qty_out")
with c3:
    st.write("")
    if st.button("Add Item"):
        if spare_item.strip():
            st.session_state.spare_parts.append({"item_name": spare_item.strip(), "quantity": spare_qty})
            st.rerun()
        else:
            st.error("Item name required")

if st.session_state.spare_parts:
    st.dataframe(pd.DataFrame(st.session_state.spare_parts), use_container_width=True, hide_index=True)
    if st.button("Clear spare parts"):
        st.session_state.spare_parts = []
        st.rerun()
