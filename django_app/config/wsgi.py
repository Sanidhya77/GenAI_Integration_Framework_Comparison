"""
WSGI config for Django experiment app.

Exposes the WSGI callable as a module-level variable named 'application'.
Gunicorn uses this as the entry point.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

# Create the SDK client at worker startup, not inside the first measured request
from common.anthropic_client import get_sync_client  # noqa: E402

get_sync_client()
