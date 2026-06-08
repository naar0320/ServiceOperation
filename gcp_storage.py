"""
Google Cloud Storage helper functions.
Handles task_reports database and image uploads/downloads.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
from google.cloud import storage
from google.oauth2 import service_account

from database_schema import CREATE_TABLE_SQL, TASK_REPORTS_TABLE

# ======================================
# Configuration
# ======================================
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
GCP_KEY_PATH = CONFIG_DIR / "gcp-key.json"

BUCKET_NAME = os.getenv("GCP_BUCKET_NAME", "ammar-builders-maintenance")
REMOTE_DB_PATH = "databases/databases_task_reports.db"
REMOTE_REGDATA_PATH = "databases/databases_regdata.db"
REMOTE_IMAGES_PREFIX = "images"


def _temp_db_path(name: str) -> Path:
    return Path(tempfile.gettempdir()) / name


def _get_credentials():
    if GCP_KEY_PATH.exists():
        return service_account.Credentials.from_service_account_file(str(GCP_KEY_PATH))
    secret_dict = st.secrets.get("gcp_service_account")
    if secret_dict:
        return service_account.Credentials.from_service_account_info(secret_dict)
    return None


@st.cache_resource
def get_gcs_client():
    """Initialize and cache Google Cloud Storage client."""
    try:
        credentials = _get_credentials()
        if not credentials:
            st.error("GCP credentials not found")
            st.error("Add config/gcp-key.json locally or gcp_service_account in Streamlit secrets")
            st.stop()
        return storage.Client(credentials=credentials)
    except Exception as e:
        st.error(f"Failed to initialize GCS client: {e}")
        st.stop()


def get_bucket():
    return get_gcs_client().bucket(BUCKET_NAME)


def _download_db_bytes(remote_path: str) -> bytes | None:
    bucket = get_bucket()
    blob = bucket.blob(remote_path)
    if not blob.exists():
        return None
    return blob.download_as_bytes()


def _upload_db_file(local_path: Path, remote_path: str) -> bool:
    bucket = get_bucket()
    blob = bucket.blob(remote_path)
    blob.upload_from_filename(str(local_path))
    return True


def _open_remote_db(remote_path: str) -> sqlite3.Connection | None:
    db_bytes = _download_db_bytes(remote_path)
    if db_bytes is None:
        return None
    temp_path = _temp_db_path(f"gcs_{remote_path.replace('/', '_')}")
    temp_path.write_bytes(db_bytes)
    return sqlite3.connect(str(temp_path))


# ======================================
# Task Reports Database
# ======================================
def download_database() -> pd.DataFrame:
    """Download task_reports table from GCS."""
    try:
        conn = _open_remote_db(REMOTE_DB_PATH)
        if conn is None:
            return pd.DataFrame()

        try:
            df = pd.read_sql_query(f'SELECT * FROM [{TASK_REPORTS_TABLE}]', conn)
            return df
        except Exception:
            return pd.DataFrame()
        finally:
            conn.close()
    except Exception as e:
        st.error(f"Failed to download database: {e}")
        return pd.DataFrame()


def _write_dataframe_to_db(df: pd.DataFrame, temp_path: Path) -> None:
    conn = sqlite3.connect(str(temp_path))
    conn.execute(CREATE_TABLE_SQL)
    df.to_sql(TASK_REPORTS_TABLE, conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()


def save_task_report(record: dict) -> bool:
    """Append or replace a task report row in GCS."""
    try:
        df = download_database()
        job_id = str(record.get("Job ID", "")).strip()

        if df.empty:
            df = pd.DataFrame([record])
        elif job_id and "Job ID" in df.columns and job_id in df["Job ID"].astype(str).values:
            idx = df.index[df["Job ID"].astype(str) == job_id][0]
            for key, value in record.items():
                if key in df.columns:
                    df.at[idx, key] = value
        else:
            df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)

        temp_path = _temp_db_path("task_reports_save.db")
        _write_dataframe_to_db(df, temp_path)
        _upload_db_file(temp_path, REMOTE_DB_PATH)
        temp_path.unlink(missing_ok=True)
        return True
    except Exception as e:
        st.error(f"Failed to save task report: {e}")
        return False


def get_task_report_by_id(job_id: str) -> dict:
    df = download_database()
    if df.empty or "Job ID" not in df.columns:
        return {}
    match = df[df["Job ID"].astype(str) == str(job_id)]
    if match.empty:
        return {}
    return match.iloc[0].to_dict()


def update_task_report(job_id: str, updates: dict) -> bool:
    record = get_task_report_by_id(job_id)
    if not record:
        return False
    record.update(updates)
    return save_task_report(record)


def generate_job_id(job_type: str = "Maintenance") -> str:
    """Generate Job ID in format YYMMDD_X_NNN (e.g. 260427_M_003)."""
    from utils import today_sg

    type_code = {"Maintenance": "M", "Repair": "R", "Inspection": "I"}.get(job_type, "M")
    date_prefix = today_sg().strftime("%y%m%d")
    prefix = f"{date_prefix}_{type_code}_"

    df = download_database()
    if df.empty or "Job ID" not in df.columns:
        return f"{prefix}001"

    today_ids = df[df["Job ID"].astype(str).str.startswith(prefix, na=False)]
    if today_ids.empty:
        return f"{prefix}001"

    max_num = 0
    for jid in today_ids["Job ID"].astype(str):
        try:
            num = int(jid.split("_")[-1])
            max_num = max(max_num, num)
        except ValueError:
            continue
    return f"{prefix}{max_num + 1:03d}"


# ======================================
# RegData & Technician List
# ======================================
def sync_regdata_from_gcs(local_path: Path) -> bool:
    try:
        db_bytes = _download_db_bytes(REMOTE_REGDATA_PATH)
        if db_bytes is None:
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(db_bytes)
        return True
    except Exception:
        return False


def get_technician_list() -> list[str]:
    """Load technician names from techlist table in regdata."""
    try:
        conn = _open_remote_db(REMOTE_REGDATA_PATH)
        if conn is None:
            return []
        try:
            df = pd.read_sql_query("SELECT name FROM techlist ORDER BY id", conn)
            return [str(n).strip() for n in df["name"].dropna() if str(n).strip()]
        except Exception:
            return []
        finally:
            conn.close()
    except Exception:
        return []


def get_user_list() -> list[str]:
    """Load user names from RegData for 'Assign by' field."""
    try:
        conn = _open_remote_db(REMOTE_REGDATA_PATH)
        if conn is None:
            return []
        try:
            df = pd.read_sql_query("SELECT name FROM RegData ORDER BY name", conn)
            return [str(n).strip() for n in df["name"].dropna() if str(n).strip()]
        except Exception:
            return []
        finally:
            conn.close()
    except Exception:
        return []


# ======================================
# Image Operations
# ======================================
def upload_image(image_bytes: bytes, job_id: str, image_type: str, index: int, ext: str = ".jpeg") -> str:
    """Upload image and return GCS path (e.g. images/260427_M_002_before_1.jpeg)."""
    try:
        bucket = get_bucket()
        remote_path = f"{REMOTE_IMAGES_PREFIX}/{job_id}_{image_type}_{index}{ext}"
        blob = bucket.blob(remote_path)
        blob.upload_from_string(image_bytes)
        return remote_path
    except Exception as e:
        st.error(f"Failed to upload image: {e}")
        return ""


def download_image(image_path: str) -> bytes:
    try:
        bucket = get_bucket()
        blob = bucket.blob(image_path)
        return blob.download_as_bytes()
    except Exception as e:
        st.error(f"Failed to download image: {e}")
        return b""


def parse_image_paths(csv_value: str) -> list[str]:
    if not csv_value or str(csv_value).strip() in ("", "NA"):
        return []
    return [p.strip() for p in str(csv_value).split(",") if p.strip()]


def list_images_for_job(job_id: str) -> list[str]:
    """List images for a job from GCS prefix and stored paths."""
    paths = set()
    try:
        bucket = get_bucket()
        for blob in bucket.list_blobs(prefix=f"{REMOTE_IMAGES_PREFIX}/{job_id}"):
            if not blob.name.endswith("/"):
                paths.add(blob.name)
    except Exception:
        pass

    record = get_task_report_by_id(job_id)
    for field in ("Before Images", "After Images"):
        paths.update(parse_image_paths(record.get(field, "")))
    return sorted(paths)


# ======================================
# Cloud Storage Browser
# ======================================
def list_uploaded_data(prefix: str = "") -> list:
    try:
        bucket = get_bucket()
        results = []
        for blob in bucket.list_blobs(prefix=prefix or ""):
            if blob.name.endswith("/"):
                continue
            results.append({
                "Path": blob.name,
                "Size (KB)": round((blob.size or 0) / 1024, 2),
                "Updated": str(blob.updated) if blob.updated else "",
                "Content Type": blob.content_type or "",
            })
        return results
    except Exception as e:
        st.error(f"Failed to list uploaded data: {e}")
        return []


def check_gcs_connection() -> bool:
    try:
        bucket = get_bucket()
        bucket.reload()
        return True
    except Exception as e:
        st.error(f"GCS Connection Error: {e}")
        return False
