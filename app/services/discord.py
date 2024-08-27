import typing as t
import urllib

import requests
from pydantic import BaseModel as Model
from requests import Session

from app import app, config
from app.db import User
from app.services import audit
from app.services.games import Game

BASE_URL = "https://discord.com"
API_URL = f"{BASE_URL}/api/v10"
CDN_URL = "https://cdn.discordapp.com"
SCOPES = ("email", "identify")

session = Session()
session.headers["Content-Type"] = "application/x-www-form-urlencoded"


class AuthorizationParams(Model):
    client_id: str = config.DISCORD_CLIENT_ID
    redirect_uri: str
    response_type: str = "code"
    scope: str = " ".join(SCOPES)
    state: str | None


def get_authorization_url(state: str = None):
    url = "https://discord.com/oauth2/authorize"
    redirect = app.url_for("discord_callback", _external=True)
    params = AuthorizationParams(state=state, redirect_uri=redirect)
    return f"{url}?" + urllib.parse.urlencode(
        params.model_dump(exclude_none=True)
    )


class AccessTokenRequest(Model):
    grant_type: str = "authorization_code"
    code: str
    redirect_uri: str


class AccessTokenResponse(Model):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    scope: str


def get_discord_token(code: str) -> AccessTokenResponse:
    url = f"{API_URL}/oauth2/token"
    data = AccessTokenRequest(
        code=code, redirect_uri=app.url_for("discord_callback", _external=True)
    )
    response = session.post(
        url,
        data=data.model_dump(),
        auth=(config.DISCORD_CLIENT_ID, config.DISCORD_CLIENT_SECRET),
    )
    response.raise_for_status()
    return AccessTokenResponse(**response.json())


class RefreshTokenRequest(Model):
    grant_type: str = "refresh_token"
    refresh_token: str


def refresh(refresh_token: str) -> AccessTokenResponse:
    url = f"{API_URL}/oauth2/token"
    data = RefreshTokenRequest(refresh_token=refresh_token)
    response = session.post(
        url,
        data=data.model_dump(),
        auth=(config.DISCORD_CLIENT_ID, config.DISCORD_CLIENT_SECRET),
    )
    response.raise_for_status()
    return AccessTokenResponse(**response.json())


class API:
    def __init__(self, access_token: str, bot=None):
        if not access_token:
            raise ValueError("Missing Discord access_token")

        self.access_token = access_token
        if bot is None:
            bot = "." in access_token
        auth_type = "Bot" if bot else "Bearer"
        self._authorization_header = f"{auth_type} {access_token}"

    def request(self, method, url: str, data=None, **kwargs):
        api = kwargs.pop("api", True)
        base = API_URL if api else BASE_URL
        url = base + url
        response = requests.request(
            method,
            url,
            params=kwargs,
            json=data,
            headers={"Authorization": self._authorization_header},
        )
        response.raise_for_status()
        if not response.text:
            return
        return response.json()

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)

    class User(Model):
        id: str
        username: str
        discriminator: str
        global_name: str | None
        avatar: str | None
        bot: bool | None = None
        system: bool | None = None
        mfa_enabled: bool | None
        banner: str | None
        accent_color: int | None
        locale: str | None
        verified: bool | None
        email: str | None
        flags: int | None
        premium_type: int | None
        public_flags: int | None
        avatar_decoration_data: dict | None

        def __str__(self):
            return self.name

        @property
        def name(self):
            return self.global_name or self.username

        @property
        def avatar_url(self):
            if not self.avatar:
                return None
            return (
                f"{CDN_URL}/avatars/{self.id}"
                f"/{self.avatar}.webp?size={config.DISCORD_AVATAR_SIZE}"
            )

    class Role(Model):
        id: str
        name: str
        position: int
        color: int

        def __str__(self):
            return self.name

    class Server(Model):
        id: str
        name: str
        roles: list["API.Role"]

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.roles.sort(key=lambda role: role.position, reverse=True)

        def get_role(self, name: str) -> t.Optional["API.Role"]:
            for role in self.roles:
                if role.name == name:
                    return role

    def get_user(self) -> "API.User":
        data = self.get("/users/@me")
        return self.User(**data)

    def get_oauth(self):
        return self.get("/oauth2/@me")

    def get_server(self, guild_id: str = config.DISCORD_SERVER_ID):
        if not guild_id:
            raise ValueError("Missing Discord server_id")

        data = self.get(f"/guilds/{guild_id}")
        return self.Server(**data)

    def get_members(self, guild_id: str = config.DISCORD_SERVER_ID):
        if not guild_id:
            raise ValueError("Missing Discord server_id")

        results = []
        after = None
        while True:
            response = self.get(
                f"/guilds/{guild_id}/members", limit=1000, after=after
            )
            if not response:
                break
            results.extend(response)
            after = response[-1]["user"]["id"]
        return results

    def get_bot(self):
        return self.get("/oauth2/applications/@me")

    def add_role(self, server_id, user_id, role_id):
        return self.put(
            f"/guilds/{server_id}/members/{user_id}/roles/{role_id}"
        )

    def remove_role(self, server_id, user_id, role_id):
        return self.delete(
            f"/guilds/{server_id}/members/{user_id}/roles/{role_id}"
        )


def get_db_user(access_token) -> User | None:
    api = API(access_token)
    user = api.get_user()
    with app.session() as s:
        user = (
            s.query(User).filter_by(discord_id=user.id)
            or s.query(User).filter_by(email=user.email)
        ).first()
    return user


def refresh_avatars(login=None):
    refreshed_users = []
    with app.session() as s:
        query = s.query(User).filter_by(image_type=User.ImageType.discord)
        if login:
            query = query.filter_by(login=login)
        for user in query:
            if not set_avatar(user):
                continue
            s.commit()
            refreshed_users.append(repr(user))
    return refreshed_users


def refresh_tokens(login=None):
    refreshed_users = []
    with app.session() as s:
        query = s.query(User).filter(User.discord_id is not None)
        if login:
            query = query.filter_by(login=login)
        for user in query:
            if not refresh_token(user):
                continue
            s.commit()
            refreshed_users.append(repr(user))
    return refreshed_users


def set_avatar(user: User) -> bool:
    """Fetches the user's current Discord"""
    api = API(user.discord_access_token)
    image = api.get_user().avatar_url
    if user.image == image:
        return False
    user.image = image
    user.image_type = User.ImageType.discord
    audit.log("Discord avatar set", user=user)
    return True


def refresh_token(user: User) -> bool:
    response = refresh(user.discord_refresh_token)
    if user.discord_access_token == response.access_token:
        return False
    user.discord_access_token = response.access_token
    user.discord_refresh_token = response.refresh_token
    return True


def _update_game_role(user: User, game: Game, action: str):
    if not user.has_discord:
        return

    # Do not crash if Discord game role update fails
    try:
        api = API(config.DISCORD_BOT_TOKEN)
        server = api.get_server()
        role = server.get_role(game.name)
        if not role:
            return
        user_id = user.discord_id
        role_id = role.id
        if action == "add":
            api.add_role(server.id, user_id, role_id)
        elif action == "remove":
            api.remove_role(server.id, user_id, role_id)
        audit.log(f"Discord game role {role} {action}ed for {user}")
    except Exception as e:
        audit.log(f"Discord game {action} error", user=user, game=game, error=e)


def add_game(user: User, game: Game):
    _update_game_role(user, game, "add")


def remove_game(user: User, game: Game):
    _update_game_role(user, game, "remove")
