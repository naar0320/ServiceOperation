import streamlit as st
from datetime import datetime, time
from pathlib import Path

from database_schema import (
    JOB_TYPES,
    SEVERITY_OPTIONS,
    PRIORITY_OPTIONS,
    LOCATION_OPTIONS,
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
    parse_image_paths,
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


def _round_time_10min(t: time) -> time:
    minute = (t.minute // 10) * 10
    return time(t.hour, minute)


def _time_slots_10min() -> list[str]:
    return [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 10, 20, 30, 40, 50)]


def _time_select_10min(label: str, default: time | None = None, key: str = "time") -> time:
    slots = _time_slots_10min()
    rounded = _round_time_10min(default or datetime.now().time())
    default_label = rounded.strftime("%H:%M")
    index = slots.index(default_label) if default_label in slots else 0
    selected = st.selectbox(label, slots, index=index, key=key)
    h, m = selected.split(":")
    return time(int(h), int(m))


def _stable_job_id(job_type: str) -> str:
    """Keep the same Job ID while filling the form; refresh when job type changes."""
    key_type = job_type or "Maintenance"
    if (
        st.session_state.get("job_entry_type") != key_type
        or "job_entry_id" not in st.session_state
    ):
        st.session_state.job_entry_type = key_type
        st.session_state.job_entry_id = generate_job_id(key_type)
    return st.session_state.job_entry_id


def _reset_job_id() -> None:
    st.session_state.pop("job_entry_id", None)
    st.session_state.pop("job_entry_type", None)


def _read_upload_bytes(uploaded_file) -> bytes:
    uploaded_file.seek(0)
    data = uploaded_file.getvalue()
    if not data:
        data = uploaded_file.read()
    return data or b""


def _upload_images(uploaded_files, job_id: str, image_type: str) -> tuple[list[str], list[str]]:
    """Upload files to GCS. Returns (paths, errors)."""
    if not uploaded_files:
        return [], []
    paths = []
    errors = []
    for i, uploaded_file in enumerate(uploaded_files, start=1):
        try:
            ext = Path(uploaded_file.name).suffix.lower() or ".jpeg"
            image_bytes = _read_upload_bytes(uploaded_file)
            if not image_bytes:
                errors.append(f"{uploaded_file.name}: file is empty")
                continue
            path = upload_image(image_bytes, job_id, image_type, i, ext)
            if path:
                paths.append(path)
            else:
                errors.append(f"{uploaded_file.name}: upload returned no path")
        except Exception as exc:
            errors.append(f"{uploaded_file.name}: {exc}")
    return paths, errors


assign_options = list(dict.fromkeys(get_technician_list() + get_user_list())) or ["No assignees loaded"]

# --- Job Type (outside form — drives image UI) ---
st.markdown("#### Job Type")
job_type = st.selectbox("Job Type *", [""] + JOB_TYPES, key="job_type_select", label_visibility="collapsed")
job_id = _stable_job_id(job_type if job_type else "Maintenance")
st.caption(f"**Job ID:** `{job_id}`")
st.info(image_requirement_label(job_type))

# --- Images OUTSIDE form (Streamlit forms block file upload on submit) ---
before_files = None
after_files = None
inspection_files = None

st.markdown("#### Images")
if job_type == "Inspection":
    min_inspection = IMAGE_RULES["Inspection"]["min_total"]
    st.caption(f"Inspection photos — min {min_inspection} when status is Completed")
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
        st.caption(f"Before — min {min_each} when Completed")
        before_files = st.file_uploader(
            "Before images",
            type=["jpg", "jpeg", "png", "gif", "webp"],
            accept_multiple_files=True,
            key="before_images",
        )
        st.caption(f"Selected: {len(before_files) if before_files else 0}/{min_each}")
    with c2:
        st.caption(f"After — min {min_each} when Completed")
        after_files = st.file_uploader(
            "After images",
            type=["jpg", "jpeg", "png", "gif", "webp"],
            accept_multiple_files=True,
            key="after_images",
        )
        st.caption(f"Selected: {len(after_files) if after_files else 0}/{min_each}")
else:
    st.caption("Select a Job Type above to show image upload fields.")

st.markdown("---")

with st.form("job_entry_form"):
    st.markdown("#### Job Classification")
    c1, c2, c3 = st.columns(3)
    with c1:
        severity = st.selectbox("Severity *", [""] + SEVERITY_OPTIONS)
    with c2:
        priority = st.selectbox("Priority *", [""] + PRIORITY_OPTIONS)
    with c3:
        location = st.selectbox("Location *", [""] + LOCATION_OPTIONS)

    st.markdown("#### Schedule & Assignment")
    c1, c2, c3 = st.columns(3)
    with c1:
        time_start = _time_select_10min("Time Start *", key="time_start")
    with c2:
        time_end = _time_select_10min("Time End", key="time_end")
    with c3:
        assign_by = st.selectbox("Assign by *", [""] + assign_options)

    job_status = st.selectbox("Job Status *", [""] + JOB_STATUS_OPTIONS)

    st.markdown("#### Task Details")
    task_description = st.text_area("Task Description *", height=100, placeholder="Describe the task")
    action = st.text_area("Action", height=80, placeholder="Action taken or planned")
    remark = st.text_area("Remark", height=60, placeholder="Additional notes")
    verify_by = st.text_input("Verify by", placeholder="Verifier name")

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
        "Location": location,
        "Job Status": job_status,
        "Assign by": assign_by,
        "Time Start": time_start.strftime("%H:%M:%S"),
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
        upload_errors = []
        with st.spinner("Uploading images to Google Cloud..."):
            if job_type == "Inspection" and inspection_files:
                paths, upload_errors = _upload_images(inspection_files, job_id, "inspection")
                record["Before Images"] = ",".join(paths)
            elif job_type in ("Maintenance", "Repair"):
                if before_files:
                    paths, errs = _upload_images(before_files, job_id, "before")
                    record["Before Images"] = ",".join(paths)
                    upload_errors.extend(errs)
                if after_files:
                    paths, errs = _upload_images(after_files, job_id, "after")
                    record["After Images"] = ",".join(paths)
                    upload_errors.extend(errs)

        total_selected = before_count + after_count + inspection_count
        total_uploaded = len(parse_image_paths(record.get("Before Images", ""))) + len(
            parse_image_paths(record.get("After Images", ""))
        )

        if upload_errors:
            st.error("Image upload errors:\n" + "\n".join(f"• {e}" for e in upload_errors))
        if total_selected > 0 and total_uploaded == 0:
            st.error("No images were uploaded to Google Cloud. Report was not saved.")
            st.stop()
        if total_selected > 0 and total_uploaded < total_selected:
            st.warning(
                f"Only {total_uploaded} of {total_selected} images uploaded. "
                "Report was not saved — please retry."
            )
            st.stop()

        with st.spinner("Saving to cloud..."):
            if save_task_report(record):
                _reset_job_id()
                st.success(f"Report saved successfully — Job ID: **{job_id}**")
                if total_uploaded:
                    st.caption(f"{total_uploaded} image(s) uploaded to GCS.")
                st.balloons()
            else:
                st.error("Failed to save report. Please try again.")
