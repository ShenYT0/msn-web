import flask
from flask_wtf import FlaskForm
from wtforms import StringField

from app import app
from app.forms import AlnumPlusValidator, DataRequired, PasswordField
from app.services import user as service


class LoginForm(FlaskForm):
    login = StringField(
        validators=[
            DataRequired(),
            AlnumPlusValidator(),
        ],
    )
    password = PasswordField(
        validators=[
            DataRequired(),
        ],
    )


@app.route("/login/")
def login():
    form = LoginForm()

    def get():
        return app.render(
            "user/login", form=form, page="login", title="Connexion"
        )

    if not form.validate_on_submit():
        return get()
    if not service.check_login(form.login.data, form.password.data):
        flask.flash("Identifiant ou mot de passe incorrect", "error")
        return get()

    if next := flask.session.pop("next", None):
        return app.redirect(next)

    return app.redirect("index")
