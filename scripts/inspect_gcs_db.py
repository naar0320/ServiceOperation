"""Inspect GCS database schemas - one-off diagnostic script."""
import sqlite3
import tempfile
from pathlib import Path

from google.cloud import storage
from google.oauth2 import service_account

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEY = PROJECT_ROOT / "config" / "gcp-key.json"

creds = service_account.Credentials.from_service_account_file(str(KEY))
client = storage.Client(credentials=creds)
bucket = client.bucket("ammar-builders-maintenance")

print("=== DATABASE FILES IN GCS ===")
for blob in bucket.list_blobs(prefix="databases/"):
    print(f"{blob.name}  ({blob.size} bytes)")

for db_name in sorted({b.name for b in bucket.list_blobs(prefix="databases/") if b.name.endswith(".db")}):
    blob = bucket.blob(db_name)
    data = blob.download_as_bytes()
    tmp = Path(tempfile.gettempdir()) / "inspect.db"
    tmp.write_bytes(data)
    conn = sqlite3.connect(str(tmp))
    cur = conn.cursor()
    print(f"\n=== {db_name} ===")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print("Tables:", tables)
    for t in tables:
        cur.execute(f'PRAGMA table_info("{t}")')
        cols = cur.fetchall()
        print(f"\n  Table: {t}")
        for c in cols:
            print(f"    {c[1]} ({c[2]})")
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        print(f"    Rows: {cur.fetchone()[0]}")
        cur.execute(f'SELECT * FROM "{t}" LIMIT 1')
        row = cur.fetchone()
        if row:
            col_names = [d[0] for d in cur.description]
            print(f"    Sample: {dict(zip(col_names, row))}")
    conn.close()
