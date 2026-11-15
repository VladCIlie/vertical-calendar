from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), default='Public')
    otp = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)
    events = db.relationship('Event', backref='creator', lazy=True)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(200), nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    recurrence = db.Column(db.String(50), nullable=True)
    tag = db.Column(db.String(100), nullable=True)
    visibility = db.Column(db.String(50), default='Public')
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    @property
    def recurrence_display(self):
        if not self.recurrence or self.recurrence == 'None':
            return None
        if self.recurrence == 'Weekly':
            return 'Weekly'
        if self.recurrence == 'Monthly':
            return 'Monthly (Same Date)'
        if self.recurrence.startswith('Monthly_Day:'):
            parts = self.recurrence.split(':')
            if len(parts) == 3:
                idx = parts[1]
                day = parts[2]
                idx_map = {'1': '1st', '2': '2nd', '3': '3rd', '4': '4th', '-1': 'Last'}
                day_map = {'MO': 'Monday', 'TU': 'Tuesday', 'WE': 'Wednesday', 'TH': 'Thursday', 'FR': 'Friday', 'SA': 'Saturday', 'SU': 'Sunday'}
                return f"{idx_map.get(idx, '')} {day_map.get(day, '')} of the month"
        return self.recurrence
    
class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    date_subscribed = db.Column(db.DateTime, default=datetime.utcnow)