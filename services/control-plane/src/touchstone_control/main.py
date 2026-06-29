"""ASGI entrypoint. Run with: uvicorn touchstone_control.main:app

In production the app is served by gunicorn with uvicorn workers (see Dockerfile)
behind a Kubernetes Service; locally `uvicorn --reload` is used.
"""

from .app import create_app

app = create_app()
