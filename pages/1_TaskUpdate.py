import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import date
from utils import (
    require_login,
    render_role_navigation,
    show_user_error,
    now_sg,
    today_sg,
)
from gcp_storage import (
    download_database,
    upload_database,
    upload_image,
)

st.set_page_config(page_title="Task Update", page_icon="🔧", layout="wide")
auth = require_login(min_level_rank=2)
render_role_navigation(auth)

# Database columns
DB_COLUMNS = [
    "Job Type",
    "Create By",
    "Create at",
    "Date",
    "Job ID",
    "Severity",
    "Priority",
    "Maintenance Frequency",
    "Shift",
    "Location",
    "Job Status",
    "Assign by",
    "Date Start",
    "Time Start",
    "Machine ID",
    "Date End",
    "Time End",
    "Machine/Equipment",
    "Task Description",
    "Action",
    "Remark",
    "Verify by",
    "Spare Parts Used",
    "Before Images",
    "After Images"
]

def _current_user() -> str:
    name = str(auth.get("name", "") or "").strip()
    user_id = str(auth.get("user_id", "") or "").strip()
    return name or user_id or "System"

def save_images(images, job_id: str, image_type: str) -> str:
    """Upload images to Google Cloud Storage"""
    if not images:
        return ""
    
    saved_paths = []
    for i, img in enumerate(images):
        ext = Path(img.name).suffix.lower()
        filename = f"{i+1}{ext}"
        image_bytes = img.getbuffer().tobytes()
        path = upload_image(image_bytes, job_id, image_type, filename)
        if path:
            saved_paths.append(path)
    
    return ",".join(saved_paths)

def generate_job_id(entry_date: date) -> str:
    """Generate next Job ID based on date"""
    date_str = entry_date.strftime("%y%m%d")
    prefix = f"{date_str}_M_"
    
    try:
        df = download_database()
        if df is not None and not df.empty and "Job ID" in df.columns:
            existing_ids = [str(x).strip() for x in df["Job ID"] if x]
            max_n = 0
            for jid in existing_ids:
                if jid.startswith(prefix):
                    tail = jid[len(prefix):].strip()
                    try:
                        max_n = max(max_n, int(tail))
                    except:
                        continue
            return f"{prefix}{(max_n + 1):03d}"
    except:
        pass
    
    return f"{prefix}001"

def load_task_data() -> pd.DataFrame:
    """Load task data from GCS"""
    try:
        df = download_database()
        return df if df is not None else pd.DataFrame(columns=DB_COLUMNS)
    except Exception as e:
        show_user_error(f"Failed to load data: {e}")
        return pd.DataFrame(columns=DB_COLUMNS)

def save_task_data(df: pd.DataFrame) -> bool:
    """Save task data to GCS"""
    try:
        return upload_database(df)
    except Exception as e:
        show_user_error(f"Failed to save data: {e}")
        return False

# ======================================
# PAGE TITLE
# ======================================
st.title("🔧 Task Update")
st.markdown("### Create New Task Report")

# ======================================
# ENTRIES ARRANGEMENT
# ======================================

# Row 1: Job Type | Create By | Create at
col1, col2, col3 = st.columns(3)
with col1:
    job_type = st.selectbox("Job Type *", [""] + ["Maintenance", "Repair", "Inspection"])
with col2:
    create_by = _current_user()
    st.text_input("Create By *", value=create_by, disabled=True)
with col3:
    st.text_input("Create at *", value=now_sg().strftime("%Y-%m-%d %H:%M:%S"), disabled=True)

# Row 2: Date | Job ID | Severity | Priority | Location
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    entry_date = st.date_input("Date *", value=today_sg())
with col2:
    job_id = generate_job_id(entry_date)
    st.text_input("Job ID *", value=job_id, disabled=True)
with col3:
    severity = st.selectbox("Severity *", [""] + ["Low", "Medium", "High", "Critical"])
with col4:
    priority = st.selectbox("Priority *", [""] + ["Low", "High"])
with col5:
    location = st.text_input("Location *")

# Row 3: Job Status | Assign by
col1, col2 = st.columns(2)
with col1:
    job_status = st.selectbox("Job Status *", [""] + ["Pending", "In Progress", "Completed"])
with col2:
    assign_by = st.text_input("Assign by *")

# Row 4: Date Start | Time Start
col1, col2 = st.columns(2)
with col1:
    date_start = st.date_input("Date Start *")
with col2:
    time_start = st.time_input("Time Start *")

# Row 5: Date End | Time End
col1, col2 = st.columns(2)
with col1:
    date_end = st.date_input("Date End *")
with col2:
    time_end = st.time_input("Time End *")

# Row 6: Machine/Equipment
machine_equipment = st.text_input("Machine/Equipment *")

# Row 7: Maintenance Frequency | Shift
col1, col2 = st.columns(2)
with col1:
    maintenance_frequency = st.selectbox("Maintenance Frequency *", [""] + ["Daily", "Weekly", "Monthly", "Quarterly", "Yearly"])
with col2:
    shift = st.selectbox("Shift *", [""] + ["Day", "Night"])

# Row 8: Machine ID
machine_id = st.text_input("Machine ID *")

# ======================================
# TASK DESCRIPTION & ACTIONS
# ======================================
st.markdown("#### 📝 Task Details")
task_description = st.text_area("Task Description *", height=100)
action = st.text_area("Action *", height=100)
remark = st.text_area("Remark", height=80)
verify_by = st.text_input("Verify by *")

# ======================================
# SPARE PARTS USED
# ======================================
st.markdown("#### 🔩 Spare Parts Used")
spare_parts = st.text_area("List spare parts used (one per line)")

# ======================================
# IMAGE UPLOADS
# ======================================
st.markdown("#### 📸 Images")

st.markdown("**Upload Images Before Maintenance (Minimum 4 images)**")
before_images = st.file_uploader(
    "Choose images (before)",
    accept_multiple_files=True,
    type=["jpg", "jpeg", "png"],
    key="before_images"
)

if before_images:
    cols = st.columns(4)
    for idx, img in enumerate(before_images[:4]):
        with cols[idx % 4]:
            st.image(img, use_column_width=True)

st.markdown("**Upload Images After Maintenance (Minimum 4 images)**")
after_images = st.file_uploader(
    "Choose images (after)",
    accept_multiple_files=True,
    type=["jpg", "jpeg", "png"],
    key="after_images"
)

if after_images:
    cols = st.columns(4)
    for idx, img in enumerate(after_images[:4]):
        with cols[idx % 4]:
            st.image(img, use_column_width=True)

# ======================================
# SAVE BUTTON
# ======================================
if st.button("💾 Save Task Report", type="primary"):
    # Validation
    if not job_type:
        show_user_error("Job Type is required")
    elif not location:
        show_user_error("Location is required")
    elif not job_status:
        show_user_error("Job Status is required")
    elif not task_description:
        show_user_error("Task Description is required")
    elif not action:
        show_user_error("Action is required")
    elif not verify_by:
        show_user_error("Verify by is required")
    elif len(before_images) < 4:
        show_user_error("Minimum 4 before images required")
    elif len(after_images) < 4:
        show_user_error("Minimum 4 after images required")
    else:
        # Upload images
        before_paths = save_images(before_images, job_id, "before")
        after_paths = save_images(after_images, job_id, "after")
        
        # Load existing data
        df = load_task_data()
        
        # Create new record
        new_record = {
            "Job Type": job_type,
            "Create By": create_by,
            "Create at": now_sg().strftime("%Y-%m-%d %H:%M:%S"),
            "Date": entry_date.strftime("%Y-%m-%d"),
            "Job ID": job_id,
            "Severity": severity,
            "Priority": priority,
            "Maintenance Frequency": maintenance_frequency,
            "Shift": shift,
            "Location": location,
            "Job Status": job_status,
            "Assign by": assign_by,
            "Date Start": date_start.strftime("%Y-%m-%d"),
            "Time Start": time_start.strftime("%H:%M:%S"),
            "Machine ID": machine_id,
            "Date End": date_end.strftime("%Y-%m-%d"),
            "Time End": time_end.strftime("%H:%M:%S"),
            "Machine/Equipment": machine_equipment,
            "Task Description": task_description,
            "Action": action,
            "Remark": remark,
            "Verify by": verify_by,
            "Spare Parts Used": spare_parts,
            "Before Images": before_paths,
            "After Images": after_paths
        }
        
        # Add to dataframe
        df = pd.concat([df, pd.DataFrame([new_record])], ignore_index=True)
        
        # Save to GCS
        if save_task_data(df):
            st.success("✅ Task report saved successfully!")
            st.balloons()
        else:
            st.error("❌ Failed to save task report")
