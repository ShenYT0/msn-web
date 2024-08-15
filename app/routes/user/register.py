from flask_wtf import FlaskForm

from app import app
from app.forms import DataRequired, LoginField, PasswordField
from app.services import user as service


class RegisterForm(FlaskForm):
    login = LoginField()
    password = PasswordField(validators=[DataRequired()])


@app.route("/register/")
def register():
    form = RegisterForm()
    if not form.validate_on_submit():
        return app.render(
            "users/register", form=form, page="login", title="Inscription"
        )
    service.register(form.login.data, form.password.data)
    return app.redirect("index")
