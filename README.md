# Ammar Builders Maintenance

Streamlit app for maintenance task reporting. Data is stored in Google Cloud Storage (SQLite databases and job images).

## Features

- **Home** — Dashboard with task counts and recent jobs (no login required)
- **Job Entry** — Create task reports with images and spare parts (Technician login)
- **Master User** — Review reports, export PDF/CSV, browse cloud storage (Admin login)

## Project structure

```
AB_taskreport_v1.0/
├── Home.py                 # Dashboard entry point
├── gcp_storage.py          # GCS database & image operations
├── pdf_report.py           # PDF report builder (required for Master User)
├── job_ticket.py           # Job submission ticket (PNG/JPEG/PDF)
├── utils.py                # Auth, timezone, validation
├── database_schema.py      # task_reports column definitions
├── requirements.txt
├── assets/
│   └── AmmarBuilder_logo.jpeg   # Company logo (sidebar, header, PDF)
├── .streamlit/
│   └── config.toml         # Streamlit config (safe to commit)
├── pages/
│   ├── 2_MasterUser.py     # Review & download reports
│   └── 3_JobEntry.py       # Job entry form
└── scripts/
    └── inspect_gcs_db.py   # Optional dev helper
```

## Local setup

```bash
cd AB_taskreport_v1.0
python -m venv .venv

# Windows
.venv\Scripts\activate
pip install -r requirements.txt

# Place your GCP service account key here (do not commit):
# config/gcp-key.json

streamlit run Home.py
```

## GCS configuration

| Setting | Value |
|---------|-------|
| Bucket | `ammar-builders-maintenance` |
| Task reports DB | `databases/databases_task_reports.db` |
| User registry DB | `databases/databases_regdata.db` |
| Images prefix | `images/` |

## GitHub — what to commit

**Include:**
- `Home.py`, `gcp_storage.py`, `pdf_report.py`, `job_ticket.py`, `utils.py`, `database_schema.py`
- `requirements.txt`, `README.md`, `.gitignore`
- `.streamlit/config.toml`
- `assets/AmmarBuilder_logo.jpeg`
- `pages/2_MasterUser.py`, `pages/3_JobEntry.py`

**Never commit:**
- `config/gcp-key.json` — GCP service account credentials
- `.streamlit/secrets.toml` — API keys and secrets
- `.venv/` — virtual environment
- `data/`, `images/` — local copies of databases and files

## Streamlit Cloud deployment

1. Push the project to GitHub (without secrets).
2. Deploy on [Streamlit Cloud](https://streamlit.io/cloud).
3. Add GCP credentials in **App settings → Secrets**:

```toml
[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

4. Set main file to `Home.py` and deploy.

## Authentication

Users log in with **User ID** and **Password** from `RegData` in `databases_regdata.db` on GCS.

| Level in RegData | Access |
|------------------|--------|
| MasterUser | Home + Job Entry + Master User |
| User | Home + Job Entry |
| Other | Home only |

**Password help (sidebar / login page):**
- **Change password** — when logged in, open *Change password* under Account
- **Forgot password** — use *Forgot password?* and enter User ID + full name from RegData
