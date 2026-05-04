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
def _clear_auth_state() -> None:
    st.session_state["is_logged_in"] = False
    st.session_state["auth_user"] = None


def _render_login_form(min_level_rank: int) -> None:
    st.warning("Login required to access this page.")
    with st.form("login_form"):
        user_id = st.text_input("User ID")
        submitted = st.form_submit_button("Login")
    if submitted:
        user_id = str(user_id or "").strip()
        if not user_id:
            st.error("User ID is required")
            return
        user_info = lookup_user_in_regdata(user_id)
        if not user_info.get("ok", False):
            st.error("Unable to verify user")
            return
        user_rank = int(user_info.get("level_rank", 1) or 1)
        if user_rank < min_level_rank:
            st.error(f"Access denied. This page requires rank {min_level_rank} or above.")
            return
        st.session_state["is_logged_in"] = True
        st.session_state["auth_user"] = {
            "user_id": user_info.get("user_id", user_id),
            "name": user_info.get("display_name", user_id.title()),
            "rank": user_rank,
        }
        st.success("Login successful")
        st.rerun()


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
        st.error(f"Access denied. This page requires rank {min_level_rank} or above.")
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
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Navigation")
    st.sidebar.page_link("Home.py", label="Home")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Account")

    if auth:
        st.sidebar.success(f"Logged in: {auth.get('name', 'User')}")
        st.sidebar.caption(f"Rank: {auth.get('rank', 1)}")
        rank = int(auth.get("rank", 1) or 1)
        if rank >= 2:
            st.sidebar.page_link("pages/1_TaskUpdate.py", label="Task Update")
        if rank >= 3:
            st.sidebar.page_link("pages/2_MasterUser.py", label="Master User")
        if st.sidebar.button("Logout"):
            _clear_auth_state()
            st.rerun()
        return auth

    with st.sidebar.form("home_login_form"):
        user_id = st.text_input("User ID", key="home_login_user_id")
        submitted = st.form_submit_button("Login for edit pages")
    if submitted:
        user_id = str(user_id or "").strip()
        if not user_id:
            st.sidebar.error("User ID is required")
        else:
            user_info = lookup_user_in_regdata(user_id)
            if not user_info.get("ok", False):
                st.sidebar.error("Unable to verify user")
            else:
                st.session_state["is_logged_in"] = True
                st.session_state["auth_user"] = {
                    "user_id": user_info.get("user_id", user_id),
                    "name": user_info.get("display_name", user_id.title()),
                    "rank": int(user_info.get("level_rank", 1) or 1),
                }
                st.sidebar.success("Login successful")
                st.rerun()
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
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**{auth.get('name', 'User')}**")
    st.sidebar.markdown(f" Rank: {auth.get('rank', 1)}")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🧭 Navigation")
    
    rank = auth.get("rank", 1)
    
    if rank >= 1:
        st.sidebar.page_link("Home.py", label="Home")
    if rank >= 2:
        st.sidebar.page_link("pages/1_TaskUpdate.py", label="Task Update")
    if rank >= 3:
        st.sidebar.page_link("pages/2_MasterUser.py", label="Master User")


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

                # Classification rules:
                # - MasterUser => full clearance (rank 3)
                # - User Level => TaskUpdate + Home (rank 2)
                # - fallback => Home only (rank 1)
                role_raw = str(
                    row_dict.get("classification")
                    or row_dict.get("level")
                    or row_dict.get("userlevel")
                    or row_dict.get("role")
                    or ""
                ).strip().lower()

                if role_raw in ("masteruser", "master user", "admin", "administrator", "manager"):
                    level_rank = 3
                elif role_raw in ("user level", "userlevel", "user", "technician", "operator"):
                    level_rank = 2
                else:
                    level_rank = 2

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
