"""One-off: migrate GCS task_reports DB to drop removed columns."""
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
from google.cloud import storage
from google.oauth2 import service_account

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database_schema import CREATE_TABLE_SQL, REMOVED_COLUMNS, TASK_REPORT_COLUMNS, TASK_REPORTS_TABLE

REMOTE_DB_PATH = "databases/databases_task_reports.db"
BUCKET_NAME = "ammar-builders-maintenance"


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.drop(columns=[c for c in REMOVED_COLUMNS if c in df.columns], errors="ignore")
    extra = [c for c in df.columns if c not in TASK_REPORT_COLUMNS]
    if extra:
        df = df.drop(columns=extra, errors="ignore")
    for col in TASK_REPORT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[TASK_REPORT_COLUMNS]


def main():
    key = ROOT / "config" / "gcp-key.json"
    creds = service_account.Credentials.from_service_account_file(str(key))
    bucket = storage.Client(credentials=creds).bucket(BUCKET_NAME)
    blob = bucket.blob(REMOTE_DB_PATH)

    if blob.exists():
        tmp = Path(tempfile.gettempdir()) / "migrate_task_reports.db"
        tmp.write_bytes(blob.download_as_bytes())
        conn = sqlite3.connect(str(tmp))
        df = pd.read_sql_query(f"SELECT * FROM [{TASK_REPORTS_TABLE}]", conn)
        conn.close()
        print(f"Before: {len(df)} rows, {len(df.columns)} columns")
        print(f"Dropping: {[c for c in REMOVED_COLUMNS if c in df.columns]}")
    else:
        df = pd.DataFrame()
        print("Database not found — creating empty schema.")

    df = normalize(df)
    out = Path(tempfile.gettempdir()) / "migrate_task_reports_out.db"
    conn = sqlite3.connect(str(out))
    conn.execute(CREATE_TABLE_SQL)
    df.to_sql(TASK_REPORTS_TABLE, conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    blob.upload_from_filename(str(out))
    print(f"After: {len(df)} rows, {len(df.columns)} columns")
    print("Columns:", list(df.columns))
    print("Migration OK.")


if __name__ == "__main__":
    main()
