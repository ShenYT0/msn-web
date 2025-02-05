import flask
from flask_login import current_user
from wtforms import (
    BooleanField,
    EmailField,
    FileField,
    SelectField,
    SubmitField,
    TextAreaField,
)

from app import app, forms
from app.db import MapPoint, User
from app.forms import DisplayNameField, Form, Length, LoginField, PasswordField
from app.services import audit, avatar
from app.services import user as service


def translate_image_type(image_type):
    translations = {
        User.ImageType.empty: "Aucun avatar",
        User.ImageType.local: "Fichier",
    }
    if image_type in translations:
        return translations[image_type]
    return image_type.capitalize().replace("_", " ")


class EditProfileForm(Form):
    login = LoginField()
    display_name = DisplayNameField()
    email = EmailField()
    bio = TextAreaField(validators=[Length(max=1000)])
    image = FileField()
    image_type = SelectField(
        choices=[(x, translate_image_type(x)) for x in User.ImageType]
    )
    map_point_id = SelectField(coerce=forms.permissive_int)
    hide_in_list = BooleanField()
    save = SubmitField()
    logout = SubmitField()
    unlink_discord = SubmitField()


@app.route("/settings/")
@service.authenticated
def settings(form: EditProfileForm):

    if form.logout.data or form.unlink_discord.data:
        form._csrf.validate_csrf_token(form, form.csrf_token)

    if form.logout.data:
        service.logout()
        flask.flash("Tu as été déconnecté")
        return app.redirect("index")

    if form.unlink_discord.data:
        if not current_user.password:
            flask.flash(
                "Tu dois définir un mot de passe pour déconnecter ton compte de"
                " Discord",
                "error",
            )
            return app.redirect("settings")

        with app.session() as s:
            user = s.query(User).get(current_user.id)
            user.discord_id = None
            user.discord_access_token = None
            user.discord_refresh_token = None
            if user.image_type == User.ImageType.discord:
                avatar.reset(user)
            s.commit()
            audit.log("Discord unlinked", user=user)
        flask.flash("Ton compte Discord a été retiré")
        return app.redirect("settings")

    with app.session() as s:
        form.map_point_id.choices = [
            ("hidden", "Masquée"),
            ("", "-----"),
            *[
                (str(mp.id), mp.name)
                for mp in sorted(
                    s.query(MapPoint).filter_by(type=MapPoint.Type.Department),
                    key=lambda mp: mp.name_normalized,
                )
            ],
            ("", "-----"),
            *[
                (str(mp.id), mp.name)
                for mp in sorted(
                    s.query(MapPoint).filter_by(type=MapPoint.Type.Country),
                    key=lambda mp: mp.name_normalized,
                )
            ],
        ]

    if not form.validate_on_submit():
        form.login.data = form.login.data or current_user.login
        form.display_name.data = (
            form.display_name.data or current_user.display_name
        )
        form.email.data = form.email.data or current_user.email
        form.bio.data = form.bio.data or current_user.bio
        form.image_type.data = form.image_type.data or current_user.image_type
        form.map_point_id.data = (
            form.map_point_id.data or current_user.map_point_id
        )
        if form.map_point_id.data:
            form.map_point_id.data = str(form.map_point_id.data)
        else:
            form.map_point_id.data = "hidden"
        form.hide_in_list.data = (
            form.hide_in_list.data or current_user.hide_in_list
        )

        if not current_user.email:
            form.image_type.choices = [
                x
                for x in form.image_type.choices
                if x[0] != User.ImageType.gravatar
            ]

        if not current_user.discord_access_token:
            form.image_type.choices = [
                x
                for x in form.image_type.choices
                if x[0] != User.ImageType.discord
            ]

        with app.session() as s:
            user = s.query(User).get(current_user.id)
            return app.render(
                "users/settings", form=form, title="Paramètres", user=user
            )

    if form.map_point_id.data == "hidden":
        form.map_point_id.data = None

    with app.session() as s:
        modified = {}
        user = s.query(User).get(current_user.id)

        for field in (
            "login",
            "email",
            "display_name",
            "bio",
            "map_point_id",
            "hide_in_list",
        ):
            if getattr(user, field) == getattr(form, field).data:
                continue
            setattr(user, field, getattr(form, field).data)
            modified[field] = True

        try:
            if avatar.update(user, form.image_type.data, form.image.data):
                modified["avatar"] = True
        except avatar.UnsupportedImageFormat:
            flask.flash("Format d'image non supporté", "error")
            return app.redirect("settings")

        if modified:
            s.commit()
            flask.flash("Profil mis à jour")
            audit.log("Profile updated", user=user, modified=modified.keys())

    return app.redirect("settings")


class PasswordForm(Form):
    password = PasswordField()
    delete = SubmitField()


@app.route("/settings/password/")
@service.authenticated
def settings_password():
    form = PasswordForm()

    if form.delete.data:
        del form.password
        if form.validate_on_submit():
            if not current_user.has_discord:
                flask.flash(
                    "Ton compte doit être lié à Discord pour pouvoir supprimer"
                    " l'authentification par mot de passe",
                    "error",
                )
                return app.redirect("settings_password")

            with app.session() as s:
                user = s.query(User).get(current_user.id)
                user.password = None
                s.commit()
                audit.log("Password deleted", user=user)
            flask.flash("Mot de passe supprimé")
            return app.redirect("settings")

    if not form.validate_on_submit():
        return app.render(
            "users/password", form=form, title="Mot de passe", page="password"
        )

    with app.session() as s:
        user = s.query(User).get(current_user.id)
        service.set_password(user, form.password.data)
        s.commit()
        audit.log("Password changed", user=user)
    flask.flash("Mot de passe mis à jour")
    return app.redirect("settings")
