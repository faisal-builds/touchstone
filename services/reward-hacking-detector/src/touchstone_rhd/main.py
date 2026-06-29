"""API entrypoint. Run with: python -m touchstone_rhd.main"""

from __future__ import annotations

import uvicorn

from .app import create_app
from .config import get_settings
from .observability.logging import configure_logging

settings = get_settings()
configure_logging(settings)
app = create_app(settings)


def main() -> None:
    uvicorn.run(app, host=settings.api_host, port=settings.api_port,
                log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
