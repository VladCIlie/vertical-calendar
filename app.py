import os
import random
import calendar
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, flash, Response, session, abort
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User, Event, Subscriber
from datetime import datetime, timedelta
import urllib.parse
from icalendar import Calendar, Event as IcalEvent
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
from dateutil import rrule

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'default_fallback_secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///church_calendar.db'
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.template_filter('urlencode')
def urlencode_filter(s):
    if s:
        return urllib.parse.quote_plus(str(s))
    return ""

@app.template_filter('gcal_date_local')
def gcal_date_local_filter(d):
    if d:
        return d.strftime('%Y%m%dT%H%M%S')
    return ""

def send_email_helper(subject, recipients, content):
    if not recipients:
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    
    # Format the sender to display a formal nickname
    sender_email = os.environ.get('SMTP_EMAIL', 'calendar@yourchurch.com')
    msg['From'] = f"Vertical Calendar <{sender_email}>"
    
    msg['Bcc'] = ", ".join(recipients)
    msg.set_content(content)
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(os.environ.get('SMTP_EMAIL', ''), os.environ.get('SMTP_PASSWORD', ''))
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"SMTP Error: {e}")
        return False

def can_view_event(event, user):
    if user.is_authenticated and user.email == 'vladilie99@gmail.com':
        return True
    if event.visibility == 'Public':
        return True
    if not user.is_authenticated:
        return False
    if event.visibility == 'Private':
        return event.creator_id == user.id
        
    role_levels = {'Public': 0, 'Member': 1, 'Leader': 2, 'Elder': 3, 'Admin': 4}
    user_level = role_levels.get(user.role, 0)
    
    if event.visibility == 'Members only' and user_level >= 1:
        return True
    if event.visibility == 'Leaders only' and user_level >= 2:
        return True
    if event.visibility == 'Elders only' and user_level >= 3:
        return True
    return False

class DisplayEvent:
    def __init__(self, id, name, description, location, start_time, end_time, recurrence_display, tag, visibility):
        self.id = id
        self.name = name
        self.description = description
        self.location = location
        self.start_time = start_time
        self.end_time = end_time
        self.recurrence_display = recurrence_display
        self.tag = tag
        self.visibility = visibility

@app.route('/')
def index():
    current_date = datetime.now()
    year = request.args.get('year', current_date.year, type=int)
    month = request.args.get('month', current_date.month, type=int)
    
    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1
        
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    month_start = datetime(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    month_end = datetime(year, month, last_day, 23, 59, 59)
    
    base_events = Event.query.all()
    events_by_day = defaultdict(list)
    unique_events_dict = {}
    
    for event in base_events:
        if not can_view_event(event, current_user):
            continue
            
        if event.recurrence == 'None' or not event.recurrence:
            if month_start <= event.start_time <= month_end:
                display_obj = DisplayEvent(event.id, event.name, event.description, event.location, event.start_time, event.end_time, event.recurrence_display, event.tag, event.visibility)
                events_by_day[event.start_time.day].append(display_obj)
                if event.id not in unique_events_dict:
                    unique_events_dict[event.id] = display_obj
        else:
            if event.start_time > month_end:
                continue
            rule = None
            if event.recurrence == 'Weekly':
                rule = rrule.rrule(rrule.WEEKLY, dtstart=event.start_time)
            elif event.recurrence == 'Monthly':
                rule = rrule.rrule(rrule.MONTHLY, dtstart=event.start_time)
            elif event.recurrence and event.recurrence.startswith('Monthly_Day:'):
                parts = event.recurrence.split(':')
                if len(parts) == 3:
                    idx = int(parts[1])
                    day_str = parts[2]
                    rrule_day = getattr(rrule, day_str)
                    rule = rrule.rrule(rrule.MONTHLY, byweekday=rrule_day(idx), dtstart=event.start_time)
                
            if rule:
                occurrences = rule.between(month_start, month_end, inc=True)
                for occ in occurrences:
                    if event.end_time:
                        duration = event.end_time - event.start_time
                        new_end = occ + duration
                    else:
                        new_end = None
                    display_obj = DisplayEvent(event.id, event.name, event.description, event.location, occ, new_end, event.recurrence_display, event.tag, event.visibility)
                    events_by_day[occ.day].append(display_obj)
                    if event.id not in unique_events_dict:
                        unique_events_dict[event.id] = display_obj
                        
    detail_events = sorted(unique_events_dict.values(), key=lambda x: x.start_time)
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]
    
    return render_template('index.html', detail_events=detail_events, cal=cal, year=year, month=month, month_name=month_name, events_by_day=events_by_day, prev_month=prev_month, prev_year=prev_year, next_month=next_month, next_year=next_year)

@app.route('/list')
def event_list():
    filter_type = request.args.get('filter', 'month')
    now = datetime.now()
    
    if filter_type == 'day':
        start_date = datetime(now.year, now.month, now.day)
        end_date = start_date + timedelta(days=1) - timedelta(seconds=1)
    elif filter_type == 'week':
        start_date = datetime(now.year, now.month, now.day) - timedelta(days=now.weekday())
        end_date = start_date + timedelta(days=7) - timedelta(seconds=1)
    elif filter_type == 'year':
        start_date = datetime(now.year, 1, 1)
        end_date = datetime(now.year, 12, 31, 23, 59, 59)
    else:
        start_date = datetime(now.year, now.month, 1)
        _, last_day = calendar.monthrange(now.year, now.month)
        end_date = datetime(now.year, now.month, last_day, 23, 59, 59)

    base_events = Event.query.all()
    expanded_events = []
    
    for event in base_events:
        if not can_view_event(event, current_user):
            continue
            
        if event.recurrence == 'None' or not event.recurrence:
            if start_date <= event.start_time <= end_date:
                expanded_events.append(DisplayEvent(event.id, event.name, event.description, event.location, event.start_time, event.end_time, event.recurrence_display, event.tag, event.visibility))
        else:
            if event.start_time > end_date:
                continue
            rule = None
            if event.recurrence == 'Weekly':
                rule = rrule.rrule(rrule.WEEKLY, dtstart=event.start_time)
            elif event.recurrence == 'Monthly':
                rule = rrule.rrule(rrule.MONTHLY, dtstart=event.start_time)
            elif event.recurrence and event.recurrence.startswith('Monthly_Day:'):
                parts = event.recurrence.split(':')
                if len(parts) == 3:
                    idx = int(parts[1])
                    day_str = parts[2]
                    rrule_day = getattr(rrule, day_str)
                    rule = rrule.rrule(rrule.MONTHLY, byweekday=rrule_day(idx), dtstart=event.start_time)
                
            if rule:
                occurrences = rule.between(start_date, end_date, inc=True)
                for occ in occurrences:
                    if event.end_time:
                        duration = event.end_time - event.start_time
                        new_end = occ + duration
                    else:
                        new_end = None
                    expanded_events.append(DisplayEvent(event.id, event.name, event.description, event.location, occ, new_end, event.recurrence_display, event.tag, event.visibility))
                    
    expanded_events.sort(key=lambda x: x.start_time)
    return render_template('list.html', events=expanded_events, current_filter=filter_type)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email').strip().lower()
        
        if User.query.filter_by(email=email).first():
            flash('This email address is already registered.', 'error')
            return redirect(url_for('register'))
            
        new_user = User(first_name=first_name, last_name=last_name, email=email)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful. You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        user = User.query.filter_by(email=email).first()
        
        if user:
            otp_code = str(random.randint(100000, 999999))
            user.otp = otp_code
            user.otp_expiry = datetime.now() + timedelta(minutes=10)
            db.session.commit()
            
            content = f"Your login verification code is: {otp_code}\n\nThis code will expire in 10 minutes."
            if send_email_helper("Your Church Calendar Login Code", [email], content):
                session['otp_email'] = email
                flash('A verification code has been sent to your email address.', 'info')
                return redirect(url_for('verify_otp'))
            else:
                flash('Failed to send email. Please check server configuration.', 'error')
        else:
            flash('Email address not found. Please register.', 'error')
    return render_template('login.html')

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('otp_email')
    if not email:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        otp_input = request.form.get('otp').strip()
        user = User.query.filter_by(email=email).first()
        
        if user and user.otp == otp_input:
            if user.otp_expiry and user.otp_expiry > datetime.now():
                login_user(user)
                user.otp = None
                user.otp_expiry = None
                session.pop('otp_email', None)
                db.session.commit()
                flash('You have logged in successfully.', 'success')
                return redirect(url_for('index'))
            else:
                flash('Your code has expired. Please request a new one.', 'error')
                return redirect(url_for('login'))
        else:
            flash('Invalid code. Please try again.', 'error')
    return render_template('verify_otp.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/panel', methods=['GET', 'POST'])
@login_required
def panel():
    if current_user.email != 'vladilie99@gmail.com':
        flash('You do not have permission to access the admin panel.', 'error')
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_user':
            email = request.form.get('email').strip().lower()
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            role = request.form.get('role')
            
            if User.query.filter_by(email=email).first():
                flash(f'User with email {email} already exists.', 'error')
            else:
                new_user = User(first_name=first_name, last_name=last_name, email=email, role=role)
                db.session.add(new_user)
                db.session.commit()
                flash(f'User {first_name} added successfully with {role} permissions.', 'success')
                
        elif action == 'update_role':
            user_id = request.form.get('user_id')
            new_role = request.form.get('role')
            user_to_update = User.query.get(user_id)
            if user_to_update and user_to_update.email != 'vladilie99@gmail.com':
                user_to_update.role = new_role
                db.session.commit()
                flash(f'Role updated for {user_to_update.first_name}.', 'success')
                
    users = User.query.order_by(User.first_name).all()
    return render_template('panel.html', users=users)

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.email == 'vladilie99@gmail.com':
        events = Event.query.order_by(Event.start_time).all()
    else:
        events = Event.query.filter_by(creator_id=current_user.id).order_by(Event.start_time).all()
    subscribers = Subscriber.query.all()
    return render_template('admin.html', events=events, subscribers=subscribers)

@app.route('/admin/add_event', methods=['POST'])
@login_required
def add_event():
    name = request.form.get('name')
    description = request.form.get('description')
    location = request.form.get('location')
    tag = request.form.get('tag')
    visibility = request.form.get('visibility')
    
    start_datetime_str = request.form.get('start_datetime')
    end_datetime_str = request.form.get('end_datetime')
    start_time = datetime.strptime(start_datetime_str, '%d/%m/%Y %H:%M')
    
    end_time = None
    if end_datetime_str and end_datetime_str.strip():
        end_time = datetime.strptime(end_datetime_str, '%d/%m/%Y %H:%M')
    
    rec_type = request.form.get('recurrence_type')
    if rec_type == 'Monthly_Day':
        idx = request.form.get('monthly_index')
        day = request.form.get('monthly_day')
        recurrence = f"Monthly_Day:{idx}:{day}"
    else:
        recurrence = rec_type
    
    new_event = Event(name=name, description=description, location=location, start_time=start_time, end_time=end_time, recurrence=recurrence, tag=tag, visibility=visibility, creator_id=current_user.id)
    db.session.add(new_event)
    db.session.commit()
    flash('Event added successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_event/<int:event_id>', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.creator_id != current_user.id and current_user.email != 'vladilie99@gmail.com':
        abort(403)
        
    if request.method == 'POST':
        event.name = request.form.get('name')
        event.description = request.form.get('description')
        event.location = request.form.get('location')
        event.tag = request.form.get('tag')
        event.visibility = request.form.get('visibility')
        
        start_datetime_str = request.form.get('start_datetime')
        end_datetime_str = request.form.get('end_datetime')
        event.start_time = datetime.strptime(start_datetime_str, '%d/%m/%Y %H:%M')
        
        if end_datetime_str and end_datetime_str.strip():
            event.end_time = datetime.strptime(end_datetime_str, '%d/%m/%Y %H:%M')
        else:
            event.end_time = None
        
        rec_type = request.form.get('recurrence_type')
        if rec_type == 'Monthly_Day':
            idx = request.form.get('monthly_index')
            day = request.form.get('monthly_day')
            event.recurrence = f"Monthly_Day:{idx}:{day}"
        else:
            event.recurrence = rec_type
            
        db.session.commit()
        flash('Event updated successfully.', 'success')
        return redirect(url_for('admin_dashboard'))

    rec_type = 'None'
    monthly_index = '1'
    monthly_day = 'MO'
    if event.recurrence:
        if event.recurrence.startswith('Monthly_Day:'):
            parts = event.recurrence.split(':')
            if len(parts) == 3:
                rec_type = 'Monthly_Day'
                monthly_index = parts[1]
                monthly_day = parts[2]
        else:
            rec_type = event.recurrence
    return render_template('edit_event.html', event=event, rec_type=rec_type, monthly_index=monthly_index, monthly_day=monthly_day)

@app.route('/admin/delete_event/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.creator_id != current_user.id and current_user.email != 'vladilie99@gmail.com':
        abort(403)
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/notify/<int:event_id>', methods=['POST'])
@login_required
def notify_subscribers(event_id):
    event = Event.query.get_or_404(event_id)
    subscribers = Subscriber.query.all()
    emails = [sub.email for sub in subscribers]
    
    content = f"This is a test notification. You are invited to the event: {event.name}, time: {event.start_time.strftime('%d/%m/%Y %H:%M')}"
    if event.location: 
        content += f", location: {event.location}"
    content += ".\n\n"
    
    if event.visibility == 'Members only':
        content += "You are reminded that this is a members only event.\n\n"
        
    if event.description: 
        content += f"{event.description}\n"
        
    if send_email_helper(f"Upcoming Church Event: {event.name}", emails, content):
        flash('Notifications sent.', 'success')
    else:
        flash('Failed to send emails.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_subscriber', methods=['POST'])
@login_required
def add_subscriber_manual():
    email = request.form.get('email')
    if not Subscriber.query.filter_by(email=email).first():
        db.session.add(Subscriber(email=email))
        db.session.commit()
        flash('Subscriber added.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form.get('email')
    if email and not Subscriber.query.filter_by(email=email).first():
        db.session.add(Subscriber(email=email))
        db.session.commit()
        flash('You have successfully subscribed.', 'success')
    return redirect(url_for('index'))

@app.route('/calendar/ics')
def download_all_ics():
    events = Event.query.all()
    cal = Calendar()
    for event in events:
        if can_view_event(event, current_user):
            ical_event = IcalEvent()
            ical_event.add('summary', event.name)
            ical_event.add('dtstart', event.start_time)
            if event.end_time: ical_event.add('dtend', event.end_time)
            if event.location: ical_event.add('location', event.location)
            if event.description: ical_event.add('description', event.description)
            cal.add_component(ical_event)
    return Response(cal.to_ical(), mimetype="text/calendar", headers={"Content-disposition": "attachment; filename=Vertical_calendar_full.ics"})

def setup_initial_admin():
    admin_email = 'vladilie99@gmail.com'
    if not User.query.filter_by(email=admin_email).first():
        admin_user = User(first_name='Admin', last_name='System', email=admin_email, role='Admin')
        db.session.add(admin_user)
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        setup_initial_admin()
    app.run(debug=True)