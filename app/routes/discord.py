import secrets

import flask
from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField

from app import app
from app.db import User
from app.forms import (
    AlnumPlusValidator,
    DataRequired,
    LoginTakenValidator,
    NotReservedNameValidator,
)
from app.services import discord as service
from app.services import user as user_service


@app.get("/login/discord/")
def discord_login():
    state = secrets.token_hex(16)
    flask.session["discord_state"] = state
    url = service.get_authorization_url(state=state)
    return flask.redirect(url)


@app.get("/login/discord/callback")
def discord_callback():
    code = flask.request.args.get("code")
    state = flask.request.args.get("state")  # noqa F841
    if not state or state != flask.session.pop("discord_state", None):
        flask.flash("Token de sécurité OAuth 2.0 State invalide.", "error")
        return app.redirect("index")
    token = service.get_discord_token(code)
    user = service.get_db_user(token.access_token)
    if not user:
        flask.session["discord_access_token"] = token.access_token
        flask.session["discord_refresh_token"] = token.refresh_token
        return app.redirect("discord_register")
    user_service.login(user)

    if next := flask.session.pop("next", None):
        return app.redirect(next)

    return app.redirect("index")


class DiscordRegisterForm(FlaskForm):
    login = StringField(
        validators=[
            DataRequired(),
            AlnumPlusValidator(),
            NotReservedNameValidator(),
            LoginTakenValidator(),
        ]
    )
    use_avatar = BooleanField()


@app.route("/register/discord/")
def discord_register():
    form = DiscordRegisterForm()

    access_token = flask.session.get("discord_access_token")
    refresh_token = flask.session.get("discord_refresh_token")

    if not access_token or not refresh_token:
        return app.redirect("register")

    api = service.API(flask.session["discord_access_token"])
    user = api.get_user()

    if not form.validate_on_submit():
        # This is the only special character allowed by Discord but not by us
        form.login.data = user.username.replace(".", "_")
        form.use_avatar.data = True
        return app.render(
            "user/discord_register",
            form=form,
            page="login",
            title="Inscription via Discord",
        )

    with app.session() as s:
        user = User(
            login=form.login.data,
            discord_id=user.id,
            discord_access_token=access_token,
            discord_refresh_token=refresh_token,
        )
        if form.use_avatar.data:
            user.image_type = User.ImageType.discord
        user.refresh_avatar()
        s.add(user)
        s.commit()
        user_service.login(user)

    if next := flask.session.pop("next", None):
        return app.redirect(next)

    return app.redirect("index")
