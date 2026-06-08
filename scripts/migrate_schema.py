"""Migrate GCS task_reports DB — drop Shift, Machine ID, Machine/Equipment."""
import sqlite3
import tempfile
from pathlib import Path

from google.cloud import storage
from google.oauth2 import service_account

ROOT = Path(__file__).resolve().parent.parent
REMOTE_DB_PATH = "databases/databases_task_reports.db"
BUCKET_NAME = "ammar-builders-maintenance"
TABLE = "task_reports"

NEW_COLUMNS = [
    "Job Type", "Create By", "Create at", "Date", "Job ID",
    "Severity", "Priority", "Maintenance Frequency", "Location", "Job Status",
    "Assign by", "Date Start", "Time Start", "Date End", "Time End",
    "Task Description", "Action", "Remark", "Verify by",
    "Spare Parts Used", "Before Images", "After Images",
]
REMOVED = {"Shift", "Machine ID", "Machine/Equipment"}


def q(name: str) -> str:
    return f"[{name}]"


def main():
    key = ROOT / "config" / "gcp-key.json"
    creds = service_account.Credentials.from_service_account_file(str(key))
    bucket = storage.Client(credentials=creds).bucket(BUCKET_NAME)
    blob = bucket.blob(REMOTE_DB_PATH)

    if not blob.exists():
        print("No database found on GCS.")
        return

    db_path = Path(tempfile.gettempdir()) / "task_reports_migrate.db"
    db_path.write_bytes(blob.download_as_bytes())

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({q(TABLE)})")
    old_cols = [r[1] for r in cur.fetchall()]
    print("Before:", len(old_cols), "columns")

    if not any(c in old_cols for c in REMOVED):
        print("Already migrated.")
        conn.close()
        return

    select_parts = []
    for c in NEW_COLUMNS:
        if c in old_cols:
            select_parts.append(q(c))
        else:
            select_parts.append(f"'' AS {q(c)}")

    create_parts = [f"{q(c)} TEXT" for c in NEW_COLUMNS]
    create_parts[4] = f"{q('Job ID')} TEXT PRIMARY KEY"  # Job ID is 5th column

    conn.execute(f"CREATE TABLE task_reports_new ({', '.join(create_parts)})")
    conn.execute(
        f"INSERT INTO task_reports_new SELECT {', '.join(select_parts)} FROM {q(TABLE)}"
    )
    conn.execute(f"DROP TABLE {q(TABLE)}")
    conn.execute("ALTER TABLE task_reports_new RENAME TO task_reports")
    conn.commit()
    conn.close()

    blob.upload_from_filename(str(db_path))
    print("After:", len(NEW_COLUMNS), "columns")
    print("Migration OK.")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({q(TABLE)})")
    print("Verified:", [r[1] for r in cur.fetchall()])
    conn.close()


if __name__ == "__main__":
    main()
