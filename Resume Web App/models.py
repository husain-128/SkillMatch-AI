from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for authentication"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="candidate")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationship to resume analyses
    analyses = db.relationship('ResumeAnalysis', backref='user', lazy=True)
    jobs = db.relationship('Job', backref='recruiter', lazy=True)
    applications = db.relationship('Application', backref='candidate', lazy=True)

    def __repr__(self):
        return f'<User {self.email}>'

class ResumeAnalysis(db.Model):
    """Resume analysis records"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resume_name = db.Column(db.String(200), nullable=False)
    job_description = db.Column(db.Text, nullable=False)
    match_score = db.Column(db.Float, nullable=False)
    matched_skills = db.Column(db.Text, nullable=True)  # JSON string
    missing_skills = db.Column(db.Text, nullable=True)  # JSON string
    explanation = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ResumeAnalysis {self.resume_name}>'

class Job(db.Model):
    """Job postings created by recruiters"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    required_skills = db.Column(db.Text, nullable=True)
    experience_level = db.Column(db.String(50), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    applications = db.relationship('Application', backref='job', lazy=True)

    def __repr__(self):
        return f'<Job {self.title}>'

class Application(db.Model):
    """Job applications submitted by candidates"""
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resume_name = db.Column(db.String(200), nullable=False)
    match_score = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(30), default="Applied")
    parsed_name = db.Column(db.String(120), nullable=True)
    parsed_email = db.Column(db.String(120), nullable=True)
    matched_skills = db.Column(db.Text, nullable=True)
    missing_skills = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    role_fit = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Application {self.id}>'

class Feedback(db.Model):
    """Optional feedback from candidates"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    rating = db.Column(db.Integer)
    comment = db.Column(db.Text)
    user = db.relationship('User', backref='feedbacks')

    def __repr__(self):
        return f'<Feedback {self.id}>'
