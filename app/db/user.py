from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

import flask
from flask_login import UserMixin

from . import Column, Id, Table, Timed, column, relation

if TYPE_CHECKING:
    from .relationships.user_game import UserGame


class User(Table, UserMixin, Id, Timed):
    class ImageType(enum.StrEnum):
        empty = enum.auto()
        local = enum.auto()
        gravatar = enum.auto()
        discord = enum.auto()

    login: Column[str] = column(unique=True)
    email: Column[str | None]
    password: Column[str | None]
    display_name: Column[str | None]
    bio: Column[str | None]
    image: Column[str | None]
    image_type: Column[ImageType] = column(default=ImageType.empty)
    last_seen: Column[datetime | None]

    discord_id: Column[str | None]
    discord_access_token: Column[str | None]
    discord_refresh_token: Column[str | None]

    hide_in_list: Column[bool] = column(default=False)

    games: Column[list[UserGame]] = relation(
        "UserGame", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"{self.__class__.__name__}(login={self.login}, id={self.id})"

    def __str__(self):
        return self.display_name or self.login

    @property
    def avatar_url(self) -> str:
        from app import config

        if self.image and self.image_type == User.ImageType.local:
            return flask.url_for("avatar", hash=self.image)
        size = config.GRAVATAR_AVATAR_SIZE
        return self.image or f"https://www.gravatar.com/avatar/?s={size}&d=mp"

    @property
    def has_discord(self) -> bool:
        return bool(self.discord_id)

    def plays(self, game_id: str) -> bool:
        return any(game.game.slug == game_id for game in self.games)

    def favorited(self, game_id: str) -> bool:
        return any(
            game.game.slug == game_id and game.favorite for game in self.games
        )
