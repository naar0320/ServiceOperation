import streamlit as st
from datetime import datetime
from pathlib import Path

from database_schema import (
    JOB_TYPES,
    SEVERITY_OPTIONS,
    PRIORITY_OPTIONS,
    FREQUENCY_OPTIONS,
    JOB_STATUS_OPTIONS,
    IMAGE_RULES,
    image_requirement_label,
    validate_job_images,
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


assign_options = list(dict.fromkeys(get_technician_list() + get_user_list())) or ["No assignees loaded"]

# Job Type outside form so image upload UI can adapt to selection
st.markdown("#### Job Type")
job_type = st.selectbox("Job Type *", [""] + JOB_TYPES, key="job_type_select", label_visibility="collapsed")
job_id = generate_job_id(job_type if job_type else "Maintenance")
st.caption(f"**Job ID:** `{job_id}`")
st.info(image_requirement_label(job_type))

with st.form("job_entry_form"):
    st.markdown("#### Job Classification")
    c1, c2 = st.columns(2)
    with c1:
        severity = st.selectbox("Severity *", [""] + SEVERITY_OPTIONS)
    with c2:
        priority = st.selectbox("Priority *", [""] + PRIORITY_OPTIONS)

    c1, c2 = st.columns(2)
    with c1:
        frequency = st.selectbox("Maintenance Frequency *", [""] + FREQUENCY_OPTIONS)
    with c2:
        location = st.text_input("Location *", placeholder="e.g. Zone 1")

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

    st.markdown("#### Task Details")
    task_description = st.text_area("Task Description *", height=100, placeholder="Describe the task")
    action = st.text_area("Action", height=80, placeholder="Action taken or planned")
    remark = st.text_area("Remark", height=60, placeholder="Additional notes")
    verify_by = st.text_input("Verify by", placeholder="Verifier name")

    st.markdown("#### Images")
    before_files = None
    after_files = None
    inspection_files = None

    if job_type == "Inspection":
        min_inspection = IMAGE_RULES["Inspection"]["min_total"]
        st.markdown(f"**Inspection photos (min {min_inspection} when Completed)**")
        inspection_files = st.file_uploader(
            "Upload inspection images",
            type=["jpg", "jpeg", "png", "gif", "webp"],
            accept_multiple_files=True,
            key="inspection_images",
        )
        st.caption(f"Selected: {len(inspection_files) if inspection_files else 0}/{min_inspection}")
    elif job_type in ("Maintenance", "Repair"):
        min_each = IMAGE_RULES[job_type]["min_before"]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Before (min {min_each} when Completed)**")
            before_files = st.file_uploader(
                "Before images",
                type=["jpg", "jpeg", "png", "gif", "webp"],
                accept_multiple_files=True,
                key="before_images",
            )
            st.caption(f"Selected: {len(before_files) if before_files else 0}/{min_each}")
        with c2:
            st.markdown(f"**After (min {min_each} when Completed)**")
            after_files = st.file_uploader(
                "After images",
                type=["jpg", "jpeg", "png", "gif", "webp"],
                accept_multiple_files=True,
                key="after_images",
            )
            st.caption(f"Selected: {len(after_files) if after_files else 0}/{min_each}")
    else:
        st.caption("Select a Job Type above to show the correct image upload fields.")

    st.markdown("#### Spare Parts Used")
    spare_text = st.text_input("Spare Parts (comma-separated or NA)", placeholder="e.g. hinge x2, bolt x4")

    submitted = st.form_submit_button("Save Report", use_container_width=True, type="primary")

if submitted:
    if not job_type:
        st.error("Job Type is required. Select it at the top of the page.")
        st.stop()

    spare_parts_value = spare_text.strip() or "NA"

    record = {
        "Job Type": job_type,
        "Create By": _current_user_name(),
        "Create at": format_ts_sg(now_sg()),
        "Date": today_sg().isoformat(),
        "Job ID": job_id,
        "Severity": severity,
        "Priority": priority,
        "Maintenance Frequency": frequency,
        "Location": location.strip(),
        "Job Status": job_status,
        "Assign by": assign_by,
        "Date Start": date_start.isoformat(),
        "Time Start": time_start.strftime("%H:%M:%S"),
        "Date End": date_end.isoformat() if date_end else "",
        "Time End": time_end.strftime("%H:%M:%S") if time_end else "",
        "Task Description": task_description.strip(),
        "Action": action.strip() or "NA",
        "Remark": remark.strip() or "NA",
        "Verify by": verify_by.strip() or "NA",
        "Spare Parts Used": spare_parts_value,
        "Before Images": "",
        "After Images": "",
    }

    require_images = job_status == "Completed"
    is_valid, errors = validate_task_report(record, require_images=False)

    before_count = len(before_files) if before_files else 0
    after_count = len(after_files) if after_files else 0
    inspection_count = len(inspection_files) if inspection_files else 0

    errors.extend(
        validate_job_images(
            job_type,
            before_count=before_count,
            after_count=after_count,
            inspection_count=inspection_count,
            require=require_images,
        )
    )

    if errors:
        st.error("Please fix the following:\n" + "\n".join(f"• {e}" for e in errors))
    else:
        with st.spinner("Uploading images..."):
            if job_type == "Inspection" and inspection_files:
                record["Before Images"] = ",".join(
                    _upload_images(inspection_files, job_id, "inspection")
                )
            elif job_type in ("Maintenance", "Repair"):
                if before_files:
                    record["Before Images"] = ",".join(
                        _upload_images(before_files, job_id, "before")
                    )
                if after_files:
                    record["After Images"] = ",".join(
                        _upload_images(after_files, job_id, "after")
                    )

        with st.spinner("Saving to cloud..."):
            if save_task_report(record):
                st.success(f"Report saved successfully — Job ID: **{job_id}**")
                st.balloons()
            else:
                st.error("Failed to save report. Please try again.")
