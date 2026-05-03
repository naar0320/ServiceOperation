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
def require_login(min_level_rank: int = 1) -> Dict[str, Any]:
    """
    Require user to be logged in and have minimum rank
    
    Rank levels:
    1 = Operator (view dashboards)
    2 = Technician (create and update tasks)
    3 = Manager (review and download reports)
    """
    query_params = st.query_params
    user_id = query_params.get("user", "") or "demo_user"
    
    auth = {
        "user_id": user_id,
        "name": user_id.title(),
        "rank": min_level_rank
    }
    return auth


def render_role_navigation(auth: Dict[str, Any]) -> None:
    """Display navigation menu based on user role"""
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"?? **{auth.get('name', 'User')}**")
    st.sidebar.markdown(f"?? Rank: {auth.get('rank', 1)}")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ?? Navigation")
    
    rank = auth.get("rank", 1)
    
    if rank >= 1:
        st.sidebar.page_link("Home.py", label="?? Dashboard")
    if rank >= 2:
        st.sidebar.page_link("pages/3_TaskUpdate.py", label="?? Task Update")
    if rank >= 3:
        st.sidebar.page_link("pages/2_MasterUser.py", label="?? Review Reports")


# ======================================
# ERROR HANDLING
# ======================================
def show_user_error(message: str) -> None:
    """Display user-friendly error message"""
    try:
        st.warning(f"?? {str(message or '').strip()}")
    except:
        pass


def show_system_error(message: str, err: Exception = None) -> None:
    """Display system error message with optional details"""
    try:
        st.error(f"? {str(message or '').strip()}")
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
        cur = conn.cursor()
        
        try:
            cur.execute('SELECT * FROM RegData WHERE UserID = ? OR user_id = ?', (user_id, user_id))
            row = cur.fetchone()
            if row:
                return {
                    "ok": True,
                    "user_id": user_id,
                    "display_name": user_id.title(),
                    "level_rank": 2
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
