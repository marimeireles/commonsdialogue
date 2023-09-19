from datetime import datetime
from flask import render_template, flash, redirect, url_for, request
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.urls import url_parse
from app import app, db
from app.forms import (
    EventForm,
    LoginForm,
    RegistrationForm,
    EditProfileForm,
    PostForm,
    ResetPasswordRequestForm,
    ResetPasswordForm,
)
from app.models import User, Post, Event, RSVP
from app.email import send_password_reset_email
from guess_language import guess_language



@app.route("/rsvp/approval/<int:rsvp_id>/<status>", methods=["GET"])
@login_required
def rsvp_approval(rsvp_id, status):
    rsvp = RSVP.query.get_or_404(rsvp_id)
    if current_user.id != rsvp.event.user_id:
        abort(403)  # Forbidden
    rsvp.status = status
    db.session.commit()
    flash("RSVP status updated.")
    return redirect(url_for("event_detail", event_id=rsvp.event_id))

@app.route("/rsvp/removal/<int:rsvp_id>", methods=["GET"])
@login_required
def rsvp_removal(rsvp_id):
    rsvp = RSVP.query.get_or_404(rsvp_id)
    if current_user.id != rsvp.event.user_id:
        abort(403)  # Forbidden
    db.session.delete(rsvp)
    db.session.commit()
    flash("RSVP removed.")
    return redirect(url_for("event_detail", event_id=rsvp.event_id))


@app.route('/rsvp/<int:event_id>', methods=['POST'])
@login_required
def rsvp(event_id):
    event = Event.query.get_or_404(event_id)
    user = current_user

    existing_rsvp = RSVP.query.filter_by(user_id=user.id, event_id=event.id).first()

    if existing_rsvp:
        flash('You have already RSVPed for this event.', 'warning')
        return redirect(url_for('event_detail', event_id=event.id))

    try:
        new_rsvp = RSVP(event_id=event.id, user_id=user.id)
        db.session.add(new_rsvp)
        db.session.commit()
        flash('Successfully RSVPed for the event!', 'success')
    except Exception as e:
        print(str(e))
        db.session.rollback()  # Roll back the transaction in case of error
        flash('Failed to RSVP for the event.', 'error')

    return redirect(url_for('event_detail', event_id=event.id))


@app.before_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        db.session.commit()


@app.route("/remove_event/<int:event_id>", methods=["POST"])
def remove_event(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash("Event successfully deleted.")
    return redirect(url_for("user_index"))


@app.route("/event/<int:event_id>", methods=["GET"])
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    return render_template("event_detail.html", event=event)


@app.route("/create_event", methods=["GET", "POST"])
@login_required
def create_event():
    form = EventForm()
    if form.validate_on_submit():
        combined_datetime = datetime.combine(form.date.data, form.time.data)
        event = Event(
            name=form.name.data,
            description=form.description.data,
            location=form.location.data,
            event_datetime=combined_datetime,
            user_id=current_user.id,
        )
        db.session.add(event)
        db.session.commit()
        flash("Your event has been created!")
        return redirect(url_for("event_detail", event_id=event.id))
    return render_template("create_event.html", form=form)


@app.route("/", methods=["GET", "POST"])
@app.route("/index", methods=["GET", "POST"])
def index():
    return render_template("index.html", title="Home")


@app.route("/user_index", methods=["GET", "POST"])
@login_required
def user_index():
    page = request.args.get("page", 1, type=int)
    upcoming_events = (
        Event.query.filter_by(user_id=current_user.id)
        .filter(Event.event_datetime > datetime.utcnow())
        .order_by(Event.event_datetime.asc())
        .paginate(page=page, per_page=10, error_out=False)
    )
    past_events = (
        Event.query.filter_by(user_id=current_user.id)
        .filter(Event.event_datetime < datetime.utcnow())
        .order_by(Event.event_datetime.desc())
        .paginate(page=page, per_page=10, error_out=False)
    )
    return render_template(
        "user_index.html", upcoming_events=upcoming_events, past_events=past_events
    )


@app.route("/explore", methods=["GET"])
def explore():
    current_time = datetime.utcnow()
    upcoming_events = (
        Event.query.filter(Event.event_datetime >= current_time)
        .order_by(Event.event_datetime.asc())
        .all()
    )
    return render_template("explore.html", upcoming_events=upcoming_events)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("user_index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password")
            return redirect(url_for("login"))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get("next")
        if not next_page or url_parse(next_page).netloc != "":
            next_page = url_for("user_index")
        return redirect(next_page)
    return render_template("login.html", title="Sign In", form=form)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("user_index"))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("Congratulations, you are now a registered user!")
        return redirect(url_for("login"))
    return render_template("register.html", title="Register", form=form)


@app.route("/user/<username>")
@login_required
def user(username):
    user = User.query.filter_by(username=username).first_or_404()
    page = request.args.get("page", 1, type=int)
    posts = user.posts.order_by(Post.timestamp.desc()).paginate(
        page=page, per_page=app.config["POSTS_PER_PAGE"], error_out=False
    )
    next_url = (
        url_for("user", username=user.username, page=posts.next_num) if posts.has_next else None
    )
    prev_url = (
        url_for("user", username=user.username, page=posts.prev_num) if posts.has_prev else None
    )
    return render_template(
        "user.html", user=user, posts=posts.items, next_url=next_url, prev_url=prev_url
    )


@app.route("/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    form = EditProfileForm(current_user.username)
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.about_me = form.about_me.data
        db.session.commit()
        flash("Your changes have been saved.")
        return redirect(url_for("edit_profile"))
    elif request.method == "GET":
        form.username.data = current_user.username
        form.about_me.data = current_user.about_me
    return render_template("edit_profile.html", title="Edit Profile", form=form)


@app.route("/follow/<username>")
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash("User {} not found.".format(username))
        return redirect(url_for("user_index"))
    if user == current_user:
        flash("You cannot follow yourself!")
        return redirect(url_for("user", username=username))
    current_user.follow(user)
    db.session.commit()
    flash("You are following {}!".format(username))
    return redirect(url_for("user", username=username))


@app.route("/unfollow/<username>")
@login_required
def unfollow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash("User {} not found.".format(username))
        return redirect(url_for("user_index"))
    if user == current_user:
        flash("You cannot unfollow yourself!")
        return redirect(url_for("user", username=username))
    current_user.unfollow(user)
    db.session.commit()
    flash("You are not following {}.".format(username))
    return redirect(url_for("user", username=username))


@app.route("/reset_password_request", methods=["GET", "POST"])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            send_password_reset_email(user)
        flash("Check your email for the instructions to reset your password")
        return redirect(url_for("login"))
    return render_template("reset_password_request.html", title="Reset Password", form=form)


@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    user = User.verify_reset_password_token(token)
    if not user:
        return redirect(url_for("index"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Your password has been reset.")
        return redirect(url_for("login"))
    return render_template("reset_password.html", form=form)
