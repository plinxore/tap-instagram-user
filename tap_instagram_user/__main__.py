"""Entry point for tap-instagram-user."""

from __future__ import annotations

from tap_instagram_user.tap import TapInstagramUser

TapInstagramUser.cli()