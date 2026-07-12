"""
Database schema for Ammar Builders Maintenance task report system.
Matches GCS databases/databases_task_reports.db structure.
"""

import sqlite3
from pathlib import Path
TASK_REPORTS_TABLE = "task_reports"

# Column definitions matching GCS task_reports table (exact names with spaces)
TASK_REPORT_COLUMNS = [
    "Job Type",
    "Create By",
    "Create at",
    "Date",
    "Job ID",
    "Severity",
    "Priority",
    "Location",
    "Job Status",
    "Attend by",
    "Time Start",
    "Time End",
    "Task Description",
    "Action",
    "Remark",
    "Verify by",
    "Spare Parts Used",
    "Before Images",
    "After Images",
]

# Form field options
JOB_TYPES = ["Maintenance", "Repair", "Inspection"]
SEVERITY_OPTIONS = ["Low", "Medium", "High", "Critical"]
PRIORITY_OPTIONS = ["Low", "Medium", "High", "Critical"]
LOCATION_OPTIONS = [
    "Main Stadium",
    "Indoor Area",
    "Aquatic Area",
    "Foyer",
    "Parking Area",
    "Stadium Walk",
]
JOB_STATUS_OPTIONS = ["Pending", "In Progress", "Completed"]

# Image requirements by job type (when Job Status is Completed)
IMAGE_RULES = {
    "Inspection": {"mode": "single", "min_total": 3, "max_total": 6},
    "Maintenance": {"mode": "before_after", "min_before": 4, "min_after": 4, "max_before": 6, "max_after": 6},
    "Repair": {"mode": "before_after", "min_before": 4, "min_after": 4, "max_before": 6, "max_after": 6},
}

# Legacy columns removed from schema (stripped on read/write)
REMOVED_COLUMNS = [
    "Shift", "Machine ID", "Machine/Equipment",
    "Date Start", "Date End", "Maintenance Frequency",
    "Assign by",
]

REQUIRED_FIELDS = [
    "Job Type",
    "Job ID",
    "Severity",
    "Priority",
    "Location",
    "Job Status",
    "Attend by",
    "Time Start",
    "Task Description",
]

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS [{TASK_REPORTS_TABLE}] (
    [Job Type] TEXT,
    [Create By] TEXT,
    [Create at] TEXT,
    [Date] TEXT,
    [Job ID] TEXT PRIMARY KEY,
    [Severity] TEXT,
    [Priority] TEXT,
    [Location] TEXT,
    [Job Status] TEXT,
    [Attend by] TEXT,
    [Time Start] TEXT,
    [Time End] TEXT,
    [Task Description] TEXT,
    [Action] TEXT,
    [Remark] TEXT,
    [Verify by] TEXT,
    [Spare Parts Used] TEXT,
    [Before Images] TEXT,
    [After Images] TEXT
)
"""


def init_database(db_path: Path) -> bool:
    """Initialize local SQLite database with task_reports schema."""
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error initializing database: {e}")
        return False


def validate_task_report(record: dict, require_images: bool = False) -> tuple[bool, list]:
    """Validate a task report record before saving."""
    errors = []

    for field in REQUIRED_FIELDS:
        value = record.get(field)
        if value is None or str(value).strip() == "":
            errors.append(f"Missing required field: {field}")

    if record.get("Job Type") and record["Job Type"] not in JOB_TYPES:
        errors.append(f"Invalid Job Type: {record['Job Type']}")

    if record.get("Job Status") and record["Job Status"] not in JOB_STATUS_OPTIONS:
        errors.append(f"Invalid Job Status: {record['Job Status']}")

    if record.get("Severity") and record["Severity"] not in SEVERITY_OPTIONS:
        errors.append(f"Invalid Severity: {record['Severity']}")

    if record.get("Priority") and record["Priority"] not in PRIORITY_OPTIONS:
        errors.append(f"Invalid Priority: {record['Priority']}")

    if record.get("Location") and record["Location"] not in LOCATION_OPTIONS:
        errors.append(f"Invalid Location: {record['Location']}")

    if require_images:
        job_type = record.get("Job Type", "")
        rules = IMAGE_RULES.get(job_type, IMAGE_RULES["Maintenance"])
        before = [p for p in str(record.get("Before Images", "")).split(",") if p.strip()]
        after = [p for p in str(record.get("After Images", "")).split(",") if p.strip()]

        if rules["mode"] == "single":
            total = len(before) + len(after)
            max_total = rules.get("max_total", 6)
            if total > max_total:
                errors.append(f"Inspection images: maximum {max_total} allowed")
            if total < rules["min_total"]:
                errors.append(
                    f"Inspection images: {total}/{rules['min_total']} required for Completed status"
                )
        else:
            max_before = rules.get("max_before", 6)
            max_after = rules.get("max_after", 6)
            if len(before) > max_before:
                errors.append(f"Before images: maximum {max_before} allowed")
            if len(after) > max_after:
                errors.append(f"After images: maximum {max_after} allowed")
            if len(before) < rules["min_before"]:
                errors.append(
                    f"Before images: {len(before)}/{rules['min_before']} required for Completed status"
                )
            if len(after) < rules["min_after"]:
                errors.append(
                    f"After images: {len(after)}/{rules['min_after']} required for Completed status"
                )

    return (len(errors) == 0, errors)


def validate_job_images(
    job_type: str,
    before_count: int,
    after_count: int,
    inspection_count: int = 0,
    require: bool = False,
) -> list[str]:
    """Return image validation errors based on job type (limits always; mins when require)."""
    if not job_type:
        return []

    rules = IMAGE_RULES.get(job_type, IMAGE_RULES["Maintenance"])
    errors = []

    if rules["mode"] == "single":
        max_total = rules.get("max_total", 6)
        if inspection_count > max_total:
            errors.append(
                f"Inspection images: {inspection_count}/{max_total} — maximum {max_total} allowed"
            )
        if require and inspection_count < rules["min_total"]:
            errors.append(
                f"Inspection images: {inspection_count}/{rules['min_total']} required for Completed status"
            )
    else:
        max_before = rules.get("max_before", 6)
        max_after = rules.get("max_after", 6)
        if before_count > max_before:
            errors.append(
                f"Before images: {before_count}/{max_before} — maximum {max_before} allowed"
            )
        if after_count > max_after:
            errors.append(
                f"After images: {after_count}/{max_after} — maximum {max_after} allowed"
            )
        if require and before_count < rules["min_before"]:
            errors.append(
                f"Before images: {before_count}/{rules['min_before']} required for Completed status"
            )
        if require and after_count < rules["min_after"]:
            errors.append(
                f"After images: {after_count}/{rules['min_after']} required for Completed status"
            )

    return errors


def image_requirement_label(job_type: str) -> str:
    """Human-readable image requirement for the form."""
    if not job_type:
        return "Select a Job Type to see image requirements."
    rules = IMAGE_RULES.get(job_type, IMAGE_RULES["Maintenance"])
    if rules["mode"] == "single":
        max_total = rules.get("max_total", 6)
        return (
            f"Inspection: **{rules['min_total']}–{max_total} images** when status is Completed "
            f"(max **{max_total}**)."
        )
    return (
        f"Maintenance/Repair: **{rules['min_before']}–{rules['max_before']} before** and "
        f"**{rules['min_after']}–{rules['max_after']} after** when status is Completed."
    )


def empty_record() -> dict:
    """Return a dict with all columns set to empty strings."""
    return {col: "" for col in TASK_REPORT_COLUMNS}
