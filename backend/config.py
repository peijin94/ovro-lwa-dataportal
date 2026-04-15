"""Configuration from environment; matches dbscripts/build_db_fnames.py conventions."""
import os
from pathlib import Path

# Project root (parent of backend/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Optional local key config (not tracked in git)
try:
    from backend import key_config  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - purely optional
    key_config = None


# Database
_kc_db_path = getattr(key_config, "LWA_DB_PATH", "") if key_config else ""
LWA_DB_PATH = os.getenv(
    "LWA_DB_PATH",
    _kc_db_path or str(PROJECT_ROOT / "dbscripts" / "lwa_data.db"),
)

# NAS roots (same as build_db_fnames.py)
SPEC_ROOT = "/common/lwa/spec_v2"
SPEC_FITS_ROOT = "/nas8/lwa/spec_v2/fits"
IMG_ROOT = "/nas7/ovro-lwa-data/hdf/slow"
MOVIES_ROOT = "/common/webplots/lwa-data/qlook_daily/movies"

ALLOWED_FILE_ROOTS = [SPEC_ROOT, SPEC_FITS_ROOT, IMG_ROOT, MOVIES_ROOT]

# Root key for file URLs (client sends root + path; we resolve to NAS path)
ROOT_KEYS = {
    "spectrum": SPEC_ROOT,
    "spectrum_fits": SPEC_FITS_ROOT,
    "imaging": IMG_ROOT,
    "movies": MOVIES_ROOT,
}

# Base URL for the deployed portal (used to build absolute links in emails, etc.)
# Default matches production host; can be overridden with PORTAL_BASE_URL env.
PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "https://ovsa.njit.edu/lwa")

# Imaging table name by data_type (lev1_mfs, lev15_fch, etc.)
DATA_TYPE_TO_TABLE = {
    "lev1_mfs": "img_lev1_mfs",
    "lev1_fch": "img_lev1_fch",
    "lev15_mfs": "img_lev15_mfs",
    "lev15_fch": "img_lev15_fch",
}

# Staging: where to write work dirs and ready zip bundles and base URL for download links
# STAGE_BASE_PATH and STAGE_URL_BASE are kept for backward compatibility but
# new code should prefer STAGE_WORK_PATH and STAGE_READY_PATH.
STAGE_BASE_PATH = Path(os.getenv("STAGE_BASE_PATH", "/home/peijin/tmpdir"))
STAGE_WORK_PATH = Path(os.getenv("STAGE_WORK_PATH", "/home/peijin/tmpdir/work"))
STAGE_READY_PATH = Path(os.getenv("STAGE_READY_PATH", "/home/peijin/tmpdir/ready"))
STAGE_URL_BASE = os.getenv("STAGE_URL_BASE", "https://ovsa.njit.edu/lwa-data/tmp/").rstrip("/") + "/"

# AI summary SQLite store
AI_SUMMARY_DB_PATH = Path(
    os.getenv("AI_SUMMARY_DB_PATH", str(PROJECT_ROOT / "llm" / "ai_summary.db"))
)

# Cloudflare Turnstile (optional; when unset, staging can be configured to reject or skip verification)
_kc_turnstile_site = getattr(key_config, "TURNSTILE_SITE_KEY", "") if key_config else ""
_kc_turnstile_secret = getattr(key_config, "TURNSTILE_SECRET_KEY", "") if key_config else ""
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", _kc_turnstile_site)
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", _kc_turnstile_secret)

# SMTP settings for staging notification emails
_kc_smtp_host = getattr(key_config, "SMTP_HOST", "") if key_config else ""
_kc_smtp_port = getattr(key_config, "SMTP_PORT", 587) if key_config else 587
_kc_smtp_user = getattr(key_config, "SMTP_USER", "") if key_config else ""
_kc_smtp_password = getattr(key_config, "SMTP_PASSWORD", "") if key_config else ""
_kc_smtp_from = getattr(key_config, "SMTP_FROM", "") if key_config else ""

SMTP_HOST = os.getenv("SMTP_HOST", _kc_smtp_host)
SMTP_PORT = int(os.getenv("SMTP_PORT", str(_kc_smtp_port)))
SMTP_USER = os.getenv("SMTP_USER", _kc_smtp_user or "ovsa.operations.noreply@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", _kc_smtp_password)
SMTP_FROM = os.getenv("SMTP_FROM", _kc_smtp_from or "ovsa.operations.noreply@gmail.com")
