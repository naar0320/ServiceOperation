"""
Utility functions for Streamlit Task Report application
Streamlined version - only essential functions for GCS-based task reporting
"""
import streamlit as st
from datetime import datetime, date, timedelta, timezone
from functools import lru_cache
from typing import Optional, Dict, Any
from pathlib import Path
import sqlite3

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


# ======================================
# DATA PATHS
# ======================================
APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = APP_ROOT / "data"
REGDATA_DB = DATA_DIR / "regdata.db"
LOGO_CANDIDATES = (
    APP_ROOT / "assets" / "AmmarBuilder_logo.jpeg",
    APP_ROOT / "assets" / "AmmarBuilder_logo.JPEG",
    APP_ROOT / "AmmarBuilder_logo.jpeg",
    APP_ROOT / "AmmarBuilder_logo.JPEG",
)


def get_logo_path() -> Optional[Path]:
    """Return the Ammar Builder logo path if the file exists."""
    for path in LOGO_CANDIDATES:
        if path.exists():
            return path
    return None


def logo_display_path() -> Optional[str]:
    """Path safe for Streamlit image/page_icon (relative, forward slashes)."""
    logo = get_logo_path()
    if not logo:
        return None
    try:
        return str(logo.relative_to(APP_ROOT)).replace("\\", "/")
    except ValueError:
        return str(logo).replace("\\", "/")


def get_page_icon():
    """Streamlit page icon — logo image or emoji fallback."""
    return logo_display_path() or "🛠️"


def render_sidebar_branding() -> None:
    """Show company logo at the top of the sidebar."""
    logo = logo_display_path()
    if logo:
        st.sidebar.image(logo, use_container_width=True)
        st.sidebar.caption("Ammar Builder Enterprise")
        st.sidebar.markdown("---")


def render_page_header(title: str, subtitle: str = "") -> None:
    """Page header with logo aligned left and title on the right."""
    logo = logo_display_path()
    if logo:
        col_logo, col_title = st.columns([1, 4], vertical_alignment="center")
        with col_logo:
            st.image(logo, use_container_width=True)
        with col_title:
            st.title(title)
            if subtitle:
                st.caption(subtitle)
    else:
        st.title(title)
        if subtitle:
            st.caption(subtitle)
    st.markdown("---")


# ======================================
# SINGAPORE TIMEZONE
# ======================================
DEFAULT_TZ = "Asia/Singapore"


@lru_cache(maxsize=1)
def _get_tz_info():
    """Get Singapore timezone info"""
    if ZoneInfo:
        try:
            return ZoneInfo(DEFAULT_TZ)
        except:
            pass
    return timezone(timedelta(hours=8))


def now_sg() -> datetime:
    """Current datetime in Singapore"""
    return datetime.now(_get_tz_info())


def today_sg() -> date:
    """Current date in Singapore"""
    return now_sg().date()


def format_ts_sg(dt: datetime = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format datetime as string"""
    if dt is None:
        dt = now_sg()
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_get_tz_info())
        else:
            dt = dt.astimezone(_get_tz_info())
        return dt.strftime(fmt)
    except:
        return str(dt)


# ======================================
# AUTHENTICATION
# ======================================
RANK_LABELS = {
    1: "Viewer",
    2: "User",
    3: "Master User",
}


def rank_from_regdata_level(role_raw: str) -> int:
    """Map RegData level/classification text to access rank."""
    role = str(role_raw or "").strip().lower()
    if role in ("masteruser", "master user", "admin", "administrator", "manager"):
        return 3
    if role in ("user level", "userlevel", "user", "technician", "operator"):
        return 2
    if role in ("viewer", "view only", "view", "readonly", "read only"):
        return 1
    return 1


def role_label_for_rank(rank: int) -> str:
    return RANK_LABELS.get(int(rank or 1), "Viewer")


def can_access_job_entry(rank: int) -> bool:
    return int(rank or 0) >= 1


def can_access_master_user(rank: int) -> bool:
    return int(rank or 0) >= 2


def can_access_cloud_database(rank: int) -> bool:
    return int(rank or 0) >= 3
def _clear_auth_state() -> None:
    st.session_state["is_logged_in"] = False
    st.session_state["auth_user"] = None
    st.session_state.pop("show_change_password", None)


def _set_auth_session(user_info: Dict[str, Any]) -> None:
    st.session_state["is_logged_in"] = True
    st.session_state["auth_user"] = {
        "user_id": user_info.get("user_id", ""),
        "name": user_info.get("display_name", "User"),
        "rank": int(user_info.get("level_rank", 1) or 1),
    }


def _attempt_login(user_id: str, password: str, min_level_rank: int) -> bool:
    from gcp_storage import authenticate_regdata_user

    user_info = authenticate_regdata_user(user_id, password)
    if not user_info.get("ok", False):
        st.error(user_info.get("error", "Invalid User ID or password."))
        return False

    user_rank = int(user_info.get("level_rank", 1) or 1)
    if user_rank < min_level_rank:
        st.error(f"Access denied. This page requires {role_label_for_rank(min_level_rank)} access or above.")
        return False

    _set_auth_session(user_info)
    st.success("Login successful")
    st.rerun()


def _render_forgot_password_panel(*, sidebar: bool = False) -> None:
    from gcp_storage import update_regdata_password, verify_regdata_identity

    container = st.sidebar if sidebar else st
    with container.expander("Forgot password?"):
        container.caption("Enter your User ID and full name exactly as stored in RegData.")
        with container.form("forgot_password_form"):
            user_id = st.text_input("User ID")
            full_name = st.text_input("Full name")
            new_password = st.text_input("New password", type="password")
            confirm_password = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Reset password")

        if submitted:
            user_id = str(user_id or "").strip()
            full_name = str(full_name or "").strip()
            if not user_id or not full_name:
                container.error("User ID and full name are required.")
            elif new_password != confirm_password:
                container.error("New passwords do not match.")
            elif not verify_regdata_identity(user_id, full_name):
                container.error("User ID and name do not match our records.")
            else:
                ok, message = update_regdata_password(user_id, new_password)
                if ok:
                    container.success(message)
                else:
                    container.error(message)


def _render_change_password_panel(auth: Dict[str, Any], *, sidebar: bool = True) -> None:
    from gcp_storage import authenticate_regdata_user, update_regdata_password

    container = st.sidebar if sidebar else st
    key_prefix = "sidebar" if sidebar else "main"

    if not st.session_state.get("show_change_password"):
        if container.button(
            "Change password",
            key=f"{key_prefix}_open_change_password",
            use_container_width=True,
        ):
            st.session_state["show_change_password"] = True
            st.rerun()
        return

    container.caption("Update your account password")
    with container.form(f"change_password_form_{key_prefix}"):
        current_password = st.text_input("Current password", type="password")
        new_password = st.text_input("New password", type="password")
        confirm_password = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update password", use_container_width=True)

    if container.button("Cancel", key=f"{key_prefix}_cancel_change_password", use_container_width=True):
        st.session_state["show_change_password"] = False
        st.rerun()

    if submitted:
        user_id = str(auth.get("user_id", "")).strip()
        if new_password != confirm_password:
            container.error("New passwords do not match.")
        else:
            check = authenticate_regdata_user(user_id, current_password)
            if not check.get("ok"):
                container.error("Current password is incorrect.")
            else:
                ok, message = update_regdata_password(user_id, new_password)
                if ok:
                    st.session_state["show_change_password"] = False
                    container.success(message)
                    st.rerun()
                else:
                    container.error(message)


def render_sidebar_account(auth: Dict[str, Any]) -> None:
    """Account actions: change password and logout."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Account")
    st.sidebar.caption(
        f"**{auth.get('name', 'User')}** · {role_label_for_rank(auth.get('rank', 1))}"
    )
    _render_change_password_panel(auth, sidebar=True)
    if st.sidebar.button("Logout", use_container_width=True, key="sidebar_logout_btn"):
        _clear_auth_state()
        st.rerun()


def _render_login_form(min_level_rank: int) -> None:
    logo = logo_display_path()
    if logo:
        st.image(logo, width=240)
    st.warning("Login required to access this page.")
    with st.form("login_form"):
        user_id = st.text_input("User ID")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
    if submitted:
        if not str(user_id or "").strip():
            st.error("User ID is required")
            return
        if not str(password or "").strip():
            st.error("Password is required")
            return
        _attempt_login(user_id, password, min_level_rank)

    _render_forgot_password_panel(sidebar=False)


def require_login(min_level_rank: int = 1) -> Dict[str, Any]:
    """
    Require user to be logged in and have minimum rank.
    """
    if "is_logged_in" not in st.session_state:
        _clear_auth_state()

    auth = st.session_state.get("auth_user") or {}
    if not st.session_state.get("is_logged_in") or not auth:
        _render_login_form(min_level_rank)
        st.stop()

    user_rank = int(auth.get("rank", 1) or 1)
    if user_rank < min_level_rank:
        st.error(f"Access denied. This page requires {role_label_for_rank(min_level_rank)} access or above.")
        st.stop()
    return auth


def get_auth_user(optional: bool = True) -> Optional[Dict[str, Any]]:
    """Return authenticated user from session without forcing login."""
    auth = st.session_state.get("auth_user")
    if st.session_state.get("is_logged_in") and auth:
        return auth
    return None if optional else {}


def render_home_auth_controls() -> Optional[Dict[str, Any]]:
    """
    Home page auth controls:
    - Home page remains accessible without login.
    - Users can login/logout here to access edit pages.
    """
    auth = get_auth_user(optional=True)
    render_sidebar_branding()
    st.sidebar.markdown("### Navigation")
    st.sidebar.page_link("Home.py", label="Home")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Account")

    if auth:
        rank = int(auth.get("rank", 1) or 1)
        if can_access_job_entry(rank):
            st.sidebar.page_link("pages/3_JobEntry.py", label="Job Entry")
        if can_access_master_user(rank):
            st.sidebar.page_link("pages/2_MasterUser.py", label="Master User")
        render_sidebar_account(auth)
        return auth

    with st.sidebar.form("home_login_form"):
        user_id = st.text_input("User ID", key="home_login_user_id")
        password = st.text_input("Password", type="password", key="home_login_password")
        submitted = st.form_submit_button("Login for edit pages")
    if submitted:
        if not str(user_id or "").strip():
            st.sidebar.error("User ID is required")
        elif not str(password or "").strip():
            st.sidebar.error("Password is required")
        else:
            from gcp_storage import authenticate_regdata_user

            user_info = authenticate_regdata_user(user_id, password)
            if not user_info.get("ok", False):
                st.sidebar.error(user_info.get("error", "Invalid User ID or password."))
            else:
                _set_auth_session(user_info)
                st.sidebar.success("Login successful")
                st.rerun()

    _render_forgot_password_panel(sidebar=True)
    st.sidebar.info("Home is available without login. Login to access additional pages.")
    return None


def hide_default_sidebar_navigation() -> None:
    """Hide Streamlit's built-in multipage nav to avoid duplicate menus."""
    st.markdown(
        """
        <style>
            [data-testid="stSidebarNav"] {display: none;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_role_navigation(auth: Dict[str, Any]) -> None:
    """Display navigation menu based on user role"""
    render_sidebar_branding()
    st.sidebar.markdown(f"**{auth.get('name', 'User')}**")
    st.sidebar.caption(role_label_for_rank(auth.get("rank", 1)))
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🧭 Navigation")
    
    rank = int(auth.get("rank", 1) or 1)
    
    st.sidebar.page_link("Home.py", label="Home")
    if can_access_job_entry(rank):
        st.sidebar.page_link("pages/3_JobEntry.py", label="Job Entry")
    if can_access_master_user(rank):
        st.sidebar.page_link("pages/2_MasterUser.py", label="Master User")

    render_sidebar_account(auth)
# ======================================
# ERROR HANDLING
# ======================================
def show_user_error(message: str) -> None:
    """Display user-friendly error message"""
    try:
        st.warning(f" {str(message or '').strip()}")
    except:
        pass


def show_system_error(message: str, err: Exception = None) -> None:
    """Display system error message with optional details"""
    try:
        st.error(f" {str(message or '').strip()}")
        if err:
            with st.expander("Error Details"):
                st.code(str(err))
    except:
        pass


# ======================================
# VALIDATION
# ======================================
def require_text(value: str, field_name: str) -> str:
    """Validate non-empty text"""
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"{field_name} is required")
    return s


def require_int(value: str, field_name: str, min_val: int = None, max_val: int = None) -> int:
    """Validate integer with optional min/max"""
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"{field_name} is required")
    try:
        n = int(float(s))
    except:
        raise ValueError(f"{field_name} must be a number")
    if min_val is not None and n < min_val:
        raise ValueError(f"{field_name} must be >= {min_val}")
    if max_val is not None and n > max_val:
        raise ValueError(f"{field_name} must be <= {max_val}")
    return n


# ======================================
# REGDATA UTILITIES (USER LOOKUP)
# ======================================
def ensure_regdata_synced() -> bool:
    """Sync regdata.db from GCS if needed"""
    try:
        from gcp_storage import sync_regdata_from_gcs
        return sync_regdata_from_gcs(REGDATA_DB)
    except:
        return REGDATA_DB.exists()


def lookup_user_in_regdata(user_id: str) -> Dict[str, Any]:
    """Lookup user in regdata.db (with GCS sync)"""
    try:
        ensure_regdata_synced()
        
        if not REGDATA_DB.exists():
            return {
                "ok": False,
                "user_id": user_id,
                "display_name": user_id.title(),
                "level_rank": 1
            }
        
        conn = sqlite3.connect(str(REGDATA_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        try:
            cur.execute("PRAGMA table_info('RegData')")
            reg_cols = [str(r[1]).strip() for r in (cur.fetchall() or [])]
            reg_cols_lower = {c.lower() for c in reg_cols}

            # Detect user-id column dynamically (schema may differ between environments)
            user_col = None
            for candidate in ("userID", "UserID", "user_id", "userid", "UserId"):
                if candidate.lower() in reg_cols_lower:
                    user_col = candidate
                    break

            if not user_col:
                return {
                    "ok": False,
                    "user_id": user_id,
                    "display_name": user_id.title(),
                    "level_rank": 1,
                    "error": "RegData user column not found",
                }

            cur.execute(f"SELECT * FROM RegData WHERE {user_col} = ? LIMIT 1", (user_id,))
            row = cur.fetchone()
            if row:
                row_dict = {k.lower(): row[k] for k in row.keys()}
                display_name = (
                    row_dict.get("name")
                    or row_dict.get("display_name")
                    or row_dict.get("fullname")
                    or user_id.title()
                )

                role_raw = str(
                    row_dict.get("classification")
                    or row_dict.get("level")
                    or row_dict.get("userlevel")
                    or row_dict.get("role")
                    or ""
                )
                level_rank = rank_from_regdata_level(role_raw)

                return {
                    "ok": True,
                    "user_id": user_id,
                    "display_name": str(display_name).strip() or user_id.title(),
                    "level_rank": level_rank
                }
        except:
            pass
        
        conn.close()
        
        return {
            "ok": True,
            "user_id": user_id,
            "display_name": user_id.title(),
            "level_rank": 1
        }
        
    except Exception as e:
        return {
            "ok": False,
            "user_id": user_id,
            "display_name": user_id.title(),
            "level_rank": 1,
            "error": str(e)
        }
