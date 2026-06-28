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

from database_schema import CREATE_TABLE_SQL, REMOVED_COLUMNS, TASK_REPORT_COLUMNS, TASK_REPORTS_TABLE
from utils import rank_from_regdata_level

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

_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


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
def _has_legacy_columns(conn: sqlite3.Connection) -> bool:
    cols = _table_columns(conn)
    return any(c in cols for c in REMOVED_COLUMNS)


def _migrate_sqlite_file(db_path: Path) -> None:
    """Rewrite SQLite file in-place to drop legacy columns and rename fields."""
    conn = sqlite3.connect(str(db_path))
    if not _has_legacy_columns(conn):
        conn.close()
        return

    old_cols = _table_columns(conn)
    select_parts = []
    for col in TASK_REPORT_COLUMNS:
        if col in old_cols:
            select_parts.append(f"[{col}]")
        elif col == "Attend by" and "Assign by" in old_cols:
            select_parts.append("[Assign by] AS [Attend by]")
        else:
            select_parts.append(f"'' AS [{col}]")

    create_parts = [f"[{col}] TEXT" for col in TASK_REPORT_COLUMNS]
    create_parts[TASK_REPORT_COLUMNS.index("Job ID")] = "[Job ID] TEXT PRIMARY KEY"

    conn.execute(f"CREATE TABLE task_reports_new ({', '.join(create_parts)})")
    conn.execute(
        f"INSERT INTO task_reports_new SELECT {', '.join(select_parts)} FROM [{TASK_REPORTS_TABLE}]"
    )
    conn.execute(f"DROP TABLE [{TASK_REPORTS_TABLE}]")
    conn.execute("ALTER TABLE task_reports_new RENAME TO task_reports")
    conn.commit()
    conn.close()


def _table_columns(conn: sqlite3.Connection) -> set:
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info([{TASK_REPORTS_TABLE}])')
    return {r[1] for r in cur.fetchall()}


def _ensure_gcs_schema_current() -> None:
    """Auto-migrate GCS database if legacy columns still exist."""
    db_bytes = _download_db_bytes(REMOTE_DB_PATH)
    if db_bytes is None:
        return
    temp_path = _temp_db_path("task_reports_check.db")
    temp_path.write_bytes(db_bytes)
    conn = sqlite3.connect(str(temp_path))
    needs_migration = _has_legacy_columns(conn)
    conn.close()
    if needs_migration:
        _migrate_sqlite_file(temp_path)
        _upload_db_file(temp_path, REMOTE_DB_PATH)
    temp_path.unlink(missing_ok=True)


def download_database() -> pd.DataFrame:
    """Download task_reports table from GCS."""
    try:
        _ensure_gcs_schema_current()
        conn = _open_remote_db(REMOTE_DB_PATH)
        if conn is None:
            return pd.DataFrame()

        try:
            df = pd.read_sql_query(f'SELECT * FROM [{TASK_REPORTS_TABLE}]', conn)
            return _normalize_dataframe(df)
        except Exception:
            return pd.DataFrame()
        finally:
            conn.close()
    except Exception as e:
        st.error(f"Failed to download database: {e}")
        return pd.DataFrame()


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Drop legacy columns and align to current schema."""
    if df.empty:
        return df
    if "Assign by" in df.columns:
        if "Attend by" not in df.columns:
            df = df.rename(columns={"Assign by": "Attend by"})
        else:
            empty = df["Attend by"].astype(str).str.strip() == ""
            df.loc[empty, "Attend by"] = df.loc[empty, "Assign by"]
        df = df.drop(columns=["Assign by"], errors="ignore")
    df = df.drop(columns=[c for c in REMOVED_COLUMNS if c in df.columns], errors="ignore")
    extra = [c for c in df.columns if c not in TASK_REPORT_COLUMNS]
    if extra:
        df = df.drop(columns=extra, errors="ignore")
    for col in TASK_REPORT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[TASK_REPORT_COLUMNS]


def _write_dataframe_to_db(df: pd.DataFrame, temp_path: Path) -> None:
    conn = sqlite3.connect(str(temp_path))
    conn.execute(CREATE_TABLE_SQL)
    _normalize_dataframe(df).to_sql(TASK_REPORTS_TABLE, conn, if_exists="replace", index=False)
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

        df = _normalize_dataframe(df)
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
def _regdata_column_map(conn: sqlite3.Connection) -> dict[str, str]:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info('RegData')")
    return {str(r[1]).strip().lower(): str(r[1]).strip() for r in cur.fetchall()}


def _pick_regdata_column(columns: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate.lower() in columns:
            return columns[candidate.lower()]
    return None


def _user_info_from_regdata_row(row: sqlite3.Row, columns: dict[str, str]) -> dict:
    row_dict = {str(k).lower(): row[k] for k in row.keys()}
    display_name = (
        row_dict.get("name")
        or row_dict.get("display_name")
        or row_dict.get("fullname")
        or row_dict.get("userid")
        or row_dict.get("user_id")
        or "User"
    )
    role_raw = str(
        row_dict.get("classification")
        or row_dict.get("level")
        or row_dict.get("userlevel")
        or row_dict.get("role")
        or ""
    )
    level_rank = rank_from_regdata_level(role_raw)

    user_id = str(row_dict.get("userid") or row_dict.get("user_id") or "").strip()
    return {
        "ok": True,
        "user_id": user_id,
        "display_name": str(display_name).strip() or user_id,
        "level_rank": level_rank,
    }


def _fetch_regdata_user(conn: sqlite3.Connection, user_id: str) -> tuple[sqlite3.Row | None, dict[str, str]]:
    columns = _regdata_column_map(conn)
    user_col = _pick_regdata_column(columns, ("userid", "user_id", "user id"))
    if not user_col:
        return None, columns
    cur = conn.cursor()
    cur.execute(f'SELECT * FROM RegData WHERE [{user_col}] = ? LIMIT 1', (user_id.strip(),))
    return cur.fetchone(), columns


def authenticate_regdata_user(user_id: str, password: str) -> dict:
    """Verify User ID and password against RegData on GCS."""
    user_id = str(user_id or "").strip()
    password = str(password or "").strip()
    if not user_id or not password:
        return {"ok": False, "error": "User ID and password are required."}

    try:
        conn = _open_remote_db(REMOTE_REGDATA_PATH)
        if conn is None:
            return {"ok": False, "error": "Unable to load user database from cloud."}
        conn.row_factory = sqlite3.Row

        row, columns = _fetch_regdata_user(conn, user_id)
        if row is None:
            conn.close()
            return {"ok": False, "error": "Invalid User ID or password."}

        pwd_col = _pick_regdata_column(columns, ("password", "passwd", "pwd"))
        if not pwd_col:
            conn.close()
            return {"ok": False, "error": "Password field not found in RegData."}

        row_dict = {str(k).lower(): row[k] for k in row.keys()}
        stored_password = str(row_dict.get(pwd_col.lower(), "") or "").strip()
        conn.close()

        if stored_password != password:
            return {"ok": False, "error": "Invalid User ID or password."}

        return _user_info_from_regdata_row(row, columns)
    except Exception as exc:
        return {"ok": False, "error": f"Login failed: {exc}"}


def verify_regdata_identity(user_id: str, full_name: str) -> bool:
    """Confirm User ID and full name match RegData (for password reset)."""
    try:
        conn = _open_remote_db(REMOTE_REGDATA_PATH)
        if conn is None:
            return False
        conn.row_factory = sqlite3.Row
        row, columns = _fetch_regdata_user(conn, user_id)
        if row is None:
            conn.close()
            return False
        row_dict = {str(k).lower(): row[k] for k in row.keys()}
        conn.close()
        expected = str(
            row_dict.get("name")
            or row_dict.get("display_name")
            or row_dict.get("fullname")
            or ""
        ).strip().lower()
        return expected == str(full_name or "").strip().lower()
    except Exception:
        return False


def update_regdata_password(user_id: str, new_password: str) -> tuple[bool, str]:
    """Update a user's password in RegData on GCS."""
    user_id = str(user_id or "").strip()
    new_password = str(new_password or "").strip()
    if not user_id or not new_password:
        return False, "User ID and new password are required."
    if len(new_password) < 6:
        return False, "Password must be at least 6 characters."

    try:
        db_bytes = _download_db_bytes(REMOTE_REGDATA_PATH)
        if db_bytes is None:
            return False, "RegData database not found on cloud."

        temp_path = _temp_db_path("regdata_password_update.db")
        temp_path.write_bytes(db_bytes)
        conn = sqlite3.connect(str(temp_path))
        columns = _regdata_column_map(conn)
        user_col = _pick_regdata_column(columns, ("userid", "user_id", "user id"))
        pwd_col = _pick_regdata_column(columns, ("password", "passwd", "pwd"))
        if not user_col or not pwd_col:
            conn.close()
            return False, "RegData user/password columns not found."

        cur = conn.cursor()
        cur.execute(
            f'UPDATE RegData SET [{pwd_col}] = ? WHERE [{user_col}] = ?',
            (new_password, user_id),
        )
        if cur.rowcount == 0:
            conn.close()
            return False, "User ID not found."

        conn.commit()
        conn.close()
        _upload_db_file(temp_path, REMOTE_REGDATA_PATH)
        temp_path.unlink(missing_ok=True)

        local_regdata = PROJECT_ROOT / "data" / "regdata.db"
        sync_regdata_from_gcs(local_regdata)
        return True, "Password updated successfully."
    except Exception as exc:
        return False, f"Could not update password: {exc}"


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
    """Load user names from RegData for the Attend by field."""
    try:
        conn = _open_remote_db(REMOTE_REGDATA_PATH)
        if conn is None:
            return []
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info('RegData')")
            cols = [str(r[1]).strip() for r in (cur.fetchall() or [])]
            cols_lower = {c.lower(): c for c in cols}

            name_col = None
            for candidate in ("name", "display_name", "fullname", "user_name"):
                if candidate in cols_lower:
                    name_col = cols_lower[candidate]
                    break
            if not name_col:
                return []

            df = pd.read_sql_query(f'SELECT DISTINCT [{name_col}] AS name FROM RegData ORDER BY name', conn)
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
    if not image_bytes:
        raise ValueError("Empty image data")
    try:
        bucket = get_bucket()
        ext = ext if ext.startswith(".") else f".{ext}"
        remote_path = f"{REMOTE_IMAGES_PREFIX}/{job_id}_{image_type}_{index}{ext}"
        blob = bucket.blob(remote_path)
        content_type = _IMAGE_CONTENT_TYPES.get(ext.lower(), "application/octet-stream")
        blob.upload_from_string(image_bytes, content_type=content_type)
        return remote_path
    except Exception as e:
        st.error(f"Failed to upload image {job_id}_{image_type}_{index}{ext}: {e}")
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


def get_gcs_bucket_summary() -> dict:
    """Return bucket metadata for the GCS database viewer."""
    try:
        bucket = get_bucket()
        bucket.reload()
        return {
            "bucket": BUCKET_NAME,
            "location": bucket.location or "—",
            "storage_class": bucket.storage_class or "—",
            "project": os.getenv("GCP_PROJECT_ID", "service-report-494512"),
            "console_url": (
                f"https://console.cloud.google.com/storage/browser/{BUCKET_NAME}"
                f"?project=service-report-494512"
            ),
        }
    except Exception as e:
        return {"bucket": BUCKET_NAME, "error": str(e)}


def list_gcs_database_files() -> list[dict]:
    """List SQLite database files under databases/ in GCS."""
    try:
        bucket = get_bucket()
        files = []
        for blob in bucket.list_blobs(prefix="databases/"):
            if blob.name.endswith("/") or not blob.name.endswith(".db"):
                continue
            files.append({
                "File": blob.name,
                "Size (KB)": round((blob.size or 0) / 1024, 2),
                "Updated": str(blob.updated) if blob.updated else "",
            })
        return sorted(files, key=lambda x: x["File"])
    except Exception as e:
        st.error(f"Failed to list database files: {e}")
        return []


def inspect_gcs_sqlite(remote_path: str) -> dict:
    """
    Download a SQLite file from GCS and return table metadata + DataFrames.
    Returns: {table_name: {"columns": [...], "row_count": int, "dataframe": df}}
    """
    try:
        db_bytes = _download_db_bytes(remote_path)
        if db_bytes is None:
            return {}

        temp_path = _temp_db_path(f"inspect_{remote_path.replace('/', '_')}")
        temp_path.write_bytes(db_bytes)
        conn = sqlite3.connect(str(temp_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]

        result = {}
        for table in tables:
            cur.execute(f'PRAGMA table_info("{table}")')
            columns = [
                {"Column": r[1], "Type": r[2], "Primary Key": "Yes" if r[5] else ""}
                for r in cur.fetchall()
            ]
            df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
            result[table] = {
                "columns": columns,
                "row_count": len(df),
                "dataframe": df,
            }
        conn.close()
        temp_path.unlink(missing_ok=True)
        return result
    except Exception as e:
        st.error(f"Failed to inspect {remote_path}: {e}")
        return {}


def count_gcs_images() -> int:
    try:
        bucket = get_bucket()
        return sum(
            1 for b in bucket.list_blobs(prefix=f"{REMOTE_IMAGES_PREFIX}/")
            if not b.name.endswith("/")
        )
    except Exception:
        return 0


def migrate_gcs_database() -> bool:
    """Rewrite GCS database using current schema (drops removed columns)."""
    try:
        df = download_database()
        if df.empty:
            temp_path = _temp_db_path("task_reports_migrate.db")
            conn = sqlite3.connect(str(temp_path))
            conn.execute(CREATE_TABLE_SQL)
            conn.commit()
            conn.close()
            _upload_db_file(temp_path, REMOTE_DB_PATH)
            temp_path.unlink(missing_ok=True)
            return True

        temp_path = _temp_db_path("task_reports_migrate.db")
        _write_dataframe_to_db(df, temp_path)
        _upload_db_file(temp_path, REMOTE_DB_PATH)
        temp_path.unlink(missing_ok=True)
        return True
    except Exception as e:
        st.error(f"Failed to migrate database: {e}")
        return False


def check_gcs_connection() -> bool:
    try:
        bucket = get_bucket()
        bucket.reload()
        return True
    except Exception as e:
        st.error(f"GCS Connection Error: {e}")
        return False
