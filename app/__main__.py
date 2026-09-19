"""Entry-Point: python -m app"""
from __future__ import annotations

from aiohttp import web

from .config import settings
from .server import create_app


def main() -> None:
    web.run_app(create_app(), host=settings.listen_host, port=settings.listen_port, print=None)


if __name__ == "__main__":
    main()
