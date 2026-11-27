"""Superset configuration (development defaults)."""
import os

SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "change-me")

_user = os.environ.get("POSTGRES_USER", "flight")
_pw = os.environ.get("POSTGRES_PASSWORD", "flight_pw")
SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg2://{_user}:{_pw}@postgres:5432/superset"

# Development convenience so scripts/setup_superset.py can use the REST API without CSRF tokens.
# Re-enable (and remove public access) before exposing Superset beyond localhost.
WTF_CSRF_ENABLED = False

# Allow dashboards to refresh as often as every 10 seconds
DASHBOARD_AUTO_REFRESH_INTERVALS = [
    [0, "Don't refresh"],
    [10, "10 seconds"],
    [30, "30 seconds"],
    [60, "1 minute"],
    [300, "5 minutes"],
]

# Let anonymous viewers open the passenger dashboard once it is published and the
# Public role is granted access (see superset/dashboards.md). Off by default.
PUBLIC_ROLE_LIKE = None
