"""
Database schema for Ammar Builders Maintenance task report system.
Matches GCS databases/databases_task_reports.db structure.
"""

import sqlite3
from pathlib import Path
from typing import Optional

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
    "After Images",
]

# Form field options
JOB_TYPES = ["Maintenance", "Repair", "Inspection"]
SEVERITY_OPTIONS = ["Low", "Medium", "High", "Critical"]
PRIORITY_OPTIONS = ["Low", "Medium", "High", "Critical"]
FREQUENCY_OPTIONS = [
    "Daily",
    "Twice a Day",
    "Weekly",
    "Bi-Weekly",
    "Monthly",
    "Quarterly",
    "Yearly",
    "As Needed",
]
SHIFT_OPTIONS = ["Day", "Night", "Morning", "Afternoon", "Evening"]
JOB_STATUS_OPTIONS = ["Pending", "In Progress", "Completed"]

REQUIRED_FIELDS = [
    "Job Type",
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
    [Maintenance Frequency] TEXT,
    [Shift] TEXT,
    [Location] TEXT,
    [Job Status] TEXT,
    [Assign by] TEXT,
    [Date Start] TEXT,
    [Time Start] TEXT,
    [Machine ID] TEXT,
    [Date End] TEXT,
    [Time End] TEXT,
    [Machine/Equipment] TEXT,
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

    if require_images:
        before = [p for p in str(record.get("Before Images", "")).split(",") if p.strip()]
        after = [p for p in str(record.get("After Images", "")).split(",") if p.strip()]
        if len(before) < 4:
            errors.append(f"Before images: {len(before)}/4 required")
        if len(after) < 4:
            errors.append(f"After images: {len(after)}/4 required")

    return (len(errors) == 0, errors)


def empty_record() -> dict:
    """Return a dict with all columns set to empty strings."""
    return {col: "" for col in TASK_REPORT_COLUMNS}
