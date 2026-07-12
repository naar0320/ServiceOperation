import hashlib
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
    get_user_list,
    parse_image_paths,
    save_task_report,
    upload_image,
)
from job_ticket import build_ticket_image, build_ticket_pdf, ticket_details
from utils import (
    format_ts_sg,
    get_page_icon,
    hide_default_sidebar_navigation,
    now_sg,
    render_page_header,
    render_role_navigation,
    require_login,
    today_sg,
)

st.set_page_config(page_title="Job Entry", page_icon=get_page_icon(), layout="wide")
hide_default_sidebar_navigation()

auth = require_login(min_level_rank=1)
render_role_navigation(auth)

render_page_header("Job Task Entry", "Create a new maintenance task report")


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
    if not job_type:
        return ""
    key_type = job_type
    prev_type = st.session_state.get("job_entry_type")
    if prev_type != key_type or "job_entry_id" not in st.session_state:
        if prev_type is not None and prev_type != key_type:
            _clear_image_stores("inspection_images", "before_images", "after_images")
        st.session_state.job_entry_type = key_type
        st.session_state.job_entry_id = generate_job_id(key_type)
    return st.session_state.job_entry_id


def _reset_job_id() -> None:
    st.session_state.pop("job_entry_id", None)
    st.session_state.pop("job_entry_type", None)


def _clear_image_stores(*bases: str) -> None:
    """Clear persisted image bytes and reset upload widgets for each list."""
    for base in bases:
        st.session_state.pop(_image_store_key(base), None)
        st.session_state.pop(_uploader_slot_key(base), None)


def _clear_image_lists(*keys: str) -> None:
    _clear_image_stores(*keys)


_FORM_WIDGET_KEYS = (
    "job_type_select",
    "time_start",
    "time_end",
    "severity",
    "priority",
    "location",
    "attend_by_select",
    "job_status",
    "task_description",
    "action",
    "remark",
    "verify_by",
    "spare_text",
    "inspection_images",
    "before_images",
    "after_images",
    "inspection_mobile",
    "before_mobile",
    "after_mobile",
)


def _clear_entry_form() -> None:
    """Reset Job Entry widgets for a fresh form."""
    _reset_job_id()
    _clear_image_lists("before_images", "after_images", "inspection_images")
    for key in _FORM_WIDGET_KEYS:
        st.session_state.pop(key, None)


def _render_completion_ticket() -> None:
    """Show submission ticket with download options."""
    ticket = st.session_state.get("job_ticket_record")
    if not ticket:
        return

    details = ticket_details(ticket)
    st.success("Job report saved to Google Cloud.")
    st.markdown("### Job submission ticket")

    col_preview, col_download = st.columns([1.2, 1])
    with col_preview:
        png_bytes = st.session_state.get("job_ticket_png")
        if png_bytes:
            st.image(png_bytes, caption="Submission ticket preview", use_container_width=True)

    with col_download:
        st.markdown("**Download ticket**")
        job_id = details.get("Job ID", "ticket")
        pdf_bytes = st.session_state.get("job_ticket_pdf")
        if pdf_bytes:
            st.download_button(
                "Download PDF",
                data=pdf_bytes,
                file_name=f"job_ticket_{job_id}.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        if png_bytes:
            st.download_button(
                "Download PNG",
                data=png_bytes,
                file_name=f"job_ticket_{job_id}.png",
                mime="image/png",
                use_container_width=True,
            )
        jpeg_bytes = st.session_state.get("job_ticket_jpeg")
        if jpeg_bytes:
            st.download_button(
                "Download JPEG",
                data=jpeg_bytes,
                file_name=f"job_ticket_{job_id}.jpeg",
                mime="image/jpeg",
                use_container_width=True,
            )

    with st.expander("Ticket details", expanded=True):
        for label, value in details.items():
            if label == "Job ID":
                st.markdown(f"**{label}:** {value}")
            else:
                st.markdown(f"**{label}:** {value}")

    st.caption("Keep this ticket for your records. Job ID is required for follow-up.")
    if st.button("Start new job entry", type="primary", use_container_width=True):
        for key in ("job_ticket_record", "job_ticket_png", "job_ticket_jpeg", "job_ticket_pdf"):
            st.session_state.pop(key, None)
        _clear_entry_form()
        st.rerun()


if st.session_state.get("job_ticket_record"):
    _render_completion_ticket()
    st.stop()


_IMAGE_TYPES = ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp"]
_PREVIEW_THUMB_W = 108
_PREVIEW_COLS = 6


def _image_store_key(base: str) -> str:
    return f"job_img_store_{base}"


def _uploader_slot_key(base: str) -> str:
    return f"job_img_slot_{base}"


def _read_upload_bytes(uploaded_file) -> bytes:
    uploaded_file.seek(0)
    data = uploaded_file.getvalue()
    if not data:
        data = uploaded_file.read()
    return data or b""


def _image_signature(name: str, data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _get_image_store(base: str) -> list[dict]:
    key = _image_store_key(base)
    if key not in st.session_state:
        st.session_state[key] = []
    return st.session_state[key]


def _add_stored_image(base: str, name: str, data: bytes, max_count: int | None = None) -> bool:
    if not data:
        return False
    store = _get_image_store(base)
    if max_count is not None and len(store) >= max_count:
        return False
    sig = _image_signature(name, data)
    if any(item["sig"] == sig for item in store):
        return False
    store.append({"name": name, "bytes": data, "sig": sig})
    return True


def _image_name(item: dict) -> str:
    return str(item.get("name") or "photo")


def _image_bytes(item: dict) -> bytes:
    return item.get("bytes") or b""


def _render_upload_previews(
    base: str,
    *,
    title: str = "Uploaded photos",
    min_required: int | None = None,
    max_allowed: int | None = None,
) -> None:
    """Small thumbnails — enough to verify photos without full-size display."""
    store = _get_image_store(base)
    count = len(store)
    if count == 0:
        st.caption("No photos added yet.")
        return

    if max_allowed is not None:
        st.caption(f"**{count} / {max_allowed}** photo{'s' if max_allowed != 1 else ''}")
    elif min_required is not None:
        st.caption(f"**{count} / {min_required}** minimum when Completed")

    st.markdown(f"**{title}** — tap **Remove** to delete a photo")
    per_row = _PREVIEW_COLS
    for row_start in range(0, count, per_row):
        row_items = store[row_start : row_start + per_row]
        cols = st.columns(len(row_items))
        for col_idx, item in enumerate(row_items):
            global_idx = row_start + col_idx
            with cols[col_idx]:
                img_bytes = _image_bytes(item)
                if img_bytes:
                    st.image(
                        img_bytes,
                        width=_PREVIEW_THUMB_W,
                        caption=f"#{global_idx + 1}",
                    )
                else:
                    st.caption(f"#{global_idx + 1}")
                st.caption(_image_name(item)[:18])
                if st.button(
                    "Remove",
                    key=f"rm_{base}_{item['sig'][:10]}_{global_idx}",
                    use_container_width=True,
                ):
                    st.session_state[_image_store_key(base)] = [
                        x for i, x in enumerate(store) if i != global_idx
                    ]
                    st.rerun()


def _image_uploader_section(
    base: str,
    label: str,
    *,
    multi: bool,
    title: str,
    min_required: int | None = None,
    max_allowed: int | None = None,
) -> list[dict]:
    """
    Copy uploads into session state immediately so photos survive page reruns.
    Resets the file picker after each successful add (desktop + mobile).
    """
    slot_key = _uploader_slot_key(base)
    slot = int(st.session_state.get(slot_key, 0))
    widget_key = f"{base}_upload_{slot}"
    store = _get_image_store(base)
    at_max = max_allowed is not None and len(store) >= max_allowed

    if at_max:
        st.caption(f"Maximum **{max_allowed}** photos reached. Remove one to add another.")
    elif multi:
        picked = st.file_uploader(
            label,
            type=_IMAGE_TYPES,
            accept_multiple_files=True,
            key=widget_key,
        )
        if picked:
            added = False
            skipped_max = False
            for uploaded in picked:
                if max_allowed is not None and len(_get_image_store(base)) >= max_allowed:
                    skipped_max = True
                    break
                data = _read_upload_bytes(uploaded)
                if _add_stored_image(base, uploaded.name, data, max_count=max_allowed):
                    added = True
            if skipped_max:
                st.warning(f"Only up to **{max_allowed}** photos allowed for this section.")
            if added or skipped_max:
                st.session_state[slot_key] = slot + 1
                st.rerun()
    else:
        picked = st.file_uploader(
            label,
            type=_IMAGE_TYPES,
            accept_multiple_files=False,
            key=widget_key,
        )
        if picked is not None:
            data = _read_upload_bytes(picked)
            if _add_stored_image(base, picked.name, data, max_count=max_allowed):
                st.session_state[slot_key] = slot + 1
                st.rerun()
            elif max_allowed is not None:
                st.warning(f"Maximum **{max_allowed}** photos allowed for this section.")

    _render_upload_previews(
        base,
        title=title,
        min_required=min_required,
        max_allowed=max_allowed,
    )

    store = _get_image_store(base)
    if store and st.button("Clear all photos", key=f"clear_{base}"):
        st.session_state[_image_store_key(base)] = []
        st.session_state[slot_key] = 0
        st.rerun()

    return store


def _upload_images(stored_items: list[dict], job_id: str, image_type: str) -> tuple[list[str], list[str]]:
    """Upload persisted image bytes to GCS. Returns (paths, errors)."""
    if not stored_items:
        return [], []
    paths = []
    errors = []
    for i, item in enumerate(stored_items, start=1):
        name = _image_name(item)
        try:
            ext = Path(name).suffix.lower() or ".jpeg"
            image_bytes = _image_bytes(item)
            if not image_bytes:
                errors.append(f"{name}: file is empty")
                continue
            path = upload_image(image_bytes, job_id, image_type, i, ext)
            if path:
                paths.append(path)
            else:
                errors.append(f"{name}: upload returned no path")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return paths, errors


regdata_names = get_user_list()

# --- Job Type (outside form — drives image UI) ---
st.markdown("#### Job Type")
job_type = st.selectbox("Job Type *", [""] + JOB_TYPES, key="job_type_select", label_visibility="collapsed")
job_id = _stable_job_id(job_type)
if job_id:
    st.caption(f"**Job ID:** `{job_id}`")
else:
    st.caption("Select a **Job Type** to generate a Job ID.")
st.info(image_requirement_label(job_type))

# --- Images OUTSIDE form (Streamlit forms block file upload on submit) ---
before_files: list[dict] = []
after_files: list[dict] = []
inspection_files: list[dict] = []

st.markdown("#### Images")
st.caption("Photos are saved in your session as you add them — they stay until you remove them or save the report.")
mobile_mode = st.toggle(
    "Mobile mode — upload one photo at a time (use this on Android phone)",
    value=False,
    help="Android Chrome often fails with multi-select. Turn this on and add photos one by one.",
)

with st.expander("Tips for Android / phone upload"):
    st.markdown(
        """
        - Turn on **Mobile mode** above and add each photo separately  
        - Pick photos from **Gallery**, not Camera (or save camera photo to gallery first)  
        - Select files within **60 seconds** after tapping Browse (Streamlit timeout on Android)  
        - If Chrome fails, try **Samsung Internet** or **Firefox**  
        - You can save with status **Pending** first (no photos required), add photos later from a PC  
        """
    )

if job_type == "Inspection":
    rules = IMAGE_RULES["Inspection"]
    min_inspection = rules["min_total"]
    max_inspection = rules.get("max_total", 6)
    st.caption(f"Inspection photos — max {max_inspection} (min {min_inspection} when Completed)")
    inspection_files = _image_uploader_section(
        "inspection_images",
        "Add inspection photo" if mobile_mode else "Upload inspection images",
        multi=not mobile_mode,
        title="Inspection photos",
        min_required=min_inspection,
        max_allowed=max_inspection,
    )
elif job_type in ("Maintenance", "Repair"):
    rules = IMAGE_RULES[job_type]
    min_each = rules["min_before"]
    max_each = rules.get("max_before", 6)
    if mobile_mode:
        st.caption(f"Before — max {max_each} (min {min_each} when Completed)")
        before_files = _image_uploader_section(
            "before_images",
            "Add BEFORE photo",
            multi=False,
            title="Before photos",
            min_required=min_each,
            max_allowed=max_each,
        )
        st.caption(f"After — max {max_each} (min {min_each} when Completed)")
        after_files = _image_uploader_section(
            "after_images",
            "Add AFTER photo",
            multi=False,
            title="After photos",
            min_required=min_each,
            max_allowed=max_each,
        )
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.caption(f"Before — max {max_each} (min {min_each} when Completed)")
            before_files = _image_uploader_section(
                "before_images",
                "Upload before images",
                multi=True,
                title="Before photos",
                min_required=min_each,
                max_allowed=max_each,
            )
        with c2:
            st.caption(f"After — max {max_each} (min {min_each} when Completed)")
            after_files = _image_uploader_section(
                "after_images",
                "Upload after images",
                multi=True,
                title="After photos",
                min_required=min_each,
                max_allowed=max_each,
            )
else:
    st.caption("Select a Job Type above to show image upload fields.")

st.markdown("---")

with st.form("job_entry_form"):
    st.markdown("#### Job Classification")
    c1, c2, c3 = st.columns(3)
    with c1:
        severity = st.selectbox("Severity *", [""] + SEVERITY_OPTIONS, key="severity")
    with c2:
        priority = st.selectbox("Priority *", [""] + PRIORITY_OPTIONS, key="priority")
    with c3:
        location = st.selectbox("Location *", [""] + LOCATION_OPTIONS, key="location")

    st.markdown("#### Schedule & Attendance")
    c1, c2 = st.columns(2)
    with c1:
        time_start = _time_select_10min("Time Start *", key="time_start")
    with c2:
        time_end = _time_select_10min("Time End", key="time_end")

    if not regdata_names:
        st.warning("No user names found in RegData. Ask admin to update `databases_regdata.db` on GCS.")
        attend_by = []
    else:
        attend_by = st.multiselect(
            "Attend by *",
            regdata_names,
            placeholder="Select one or more names from RegData",
            help="Choose all staff who attended this job.",
            key="attend_by_select",
        )
        if attend_by:
            st.caption(f"Selected: {', '.join(attend_by)}")

    job_status = st.selectbox("Job Status *", [""] + JOB_STATUS_OPTIONS, key="job_status")

    st.markdown("#### Task Details")
    task_description = st.text_area("Task Description *", height=100, placeholder="Describe the task", key="task_description")
    action = st.text_area("Action", height=80, placeholder="Action taken or planned", key="action")
    remark = st.text_area("Remark", height=60, placeholder="Additional notes", key="remark")
    verify_by = st.text_input("Verify by", placeholder="Verifier name", key="verify_by")

    st.markdown("#### Spare Parts Used")
    spare_text = st.text_input("Spare Parts (comma-separated or NA)", placeholder="e.g. hinge x2, bolt x4", key="spare_text")

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
        "Attend by": ", ".join(attend_by),
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

    before_count = len(before_files)
    after_count = len(after_files)
    inspection_count = len(inspection_files)

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
                st.session_state["job_ticket_record"] = record.copy()
                st.session_state["job_ticket_png"] = build_ticket_image(record, "PNG")
                st.session_state["job_ticket_jpeg"] = build_ticket_image(record, "JPEG")
                st.session_state["job_ticket_pdf"] = build_ticket_pdf(record).getvalue()
                _clear_entry_form()
                st.rerun()
            else:
                st.error("Failed to save report. Please try again.")
