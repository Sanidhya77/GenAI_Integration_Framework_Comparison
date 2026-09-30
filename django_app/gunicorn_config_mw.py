"""
Gunicorn configuration for Django, multi-worker arm (MULTIWORKER=1 only).

Same as gunicorn_config.py except the worker count: workers = 2 x nproc + 1
(the Gunicorn documentation's rule of thumb), sync worker class, 1 thread each.
Recorded as django_mw. Used with the simulator only.

Run command:
  cd /home/sanidhya/experiment/django_app
  gunicorn -c gunicorn_config_mw.py config.wsgi:application
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Server socket
bind = "0.0.0.0:8000"

# Worker processes
workers = 2 * len(os.sched_getaffinity(0)) + 1
worker_class = "sync"     # Default synchronous worker (WSGI)
threads = 1               # Single thread per worker

# Timeouts (same as the single-worker configuration)
timeout = 600
graceful_timeout = 30
keepalive = 5

# Logging (same as the single-worker configuration)
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Server mechanics
preload_app = False
