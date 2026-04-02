from flask import Flask, request, render_template, flash, redirect, url_for, send_from_directory, Response
import urllib.request
import csv
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pypdf import PdfReader
import string
import re
import json
import secrets
from datetime import datetime
from functools import wraps
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text
from models import db, User, ResumeAnalysis, Job, Application, Feedback
from flask_login import LoginManager, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)  # Change in production
# Always use a single stable database file. If DATABASE_PATH is provided
# (for example on Render with a persistent disk), prefer that location.
os.makedirs(app.instance_path, exist_ok=True)
db_path = os.getenv('DATABASE_PATH', os.path.join(app.instance_path, 'database.db'))
db_path_uri = db_path.replace('\\', '/')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB max upload size
app.config['UPLOAD_FOLDER'] = 'uploads'

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Predefined list of common skills
SKILLS_LIST = [
    'python', 'java', 'javascript', 'machine learning', 'data analysis',
    'sql', 'html', 'css', 'react', 'flask', 'tensorflow', 'pandas',
    'numpy', 'git', 'docker', 'aws', 'linux', 'c++', 'r', 'excel',
    'mongodb', 'php', 'mysql', 'node.js', 'angular', 'vue', 'django',
    'spring', 'kubernetes', 'azure', 'gcp', 'postgresql', 'oracle',
    'c#', 'ruby', 'rails', 'scala', 'hadoop', 'spark', 'tableau',
    'power bi', 'sas', 'matlab', 'swift', 'kotlin', 'flutter', 'ionic',
    'firebase', 'heroku', 'jenkins', 'ansible', 'terraform', 'graphql',
    'rest api', 'soap', 'xml', 'json', 'linux', 'windows', 'macos',
    'bash', 'powershell', 'vim', 'emacs', 'intellij', 'vscode', 'eclipse'
]

# Role helpers
def is_admin_user():
    return current_user.is_authenticated and (
        current_user.role == 'admin' or current_user.email == '2005hussainvanak@gmail.com'
    )

def require_roles(*roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles and not is_admin_user():
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('index'))
            return func(*args, **kwargs)
        return wrapper
    return decorator

def parse_required_skills(skills_text):
    if not skills_text:
        return []
    parts = skills_text.replace('\n', ',').split(',')
    cleaned = []
    for item in parts:
        skill = item.strip().lower()
        if skill and skill not in cleaned:
            cleaned.append(skill)
    return cleaned

# Ensure uploads folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def normalize_text(text):
    """Normalize text: lowercase, remove punctuation, strip extra whitespace."""
    text = text.lower()
    text = text.translate(str.maketrans('', '', string.punctuation))
    return ' '.join(text.split())

def extract_text_from_pdf(file_path):
    """Extract text from PDF using PyPDF2."""
    try:
        reader = PdfReader(file_path)
        text = ''
        for page in reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        return None

def extract_email(text):
    match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]+", text)
    return match.group(0) if match else "Not Found"

def extract_name(text):
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return lines[0] if lines else "Unknown"

def get_skills_in_text(text, skills_list):
    """Find skills in text using case-insensitive substring match."""
    text_lower = text.lower()
    found = []
    for skill in skills_list:
        skill_lower = skill.lower()
        # If skill is alphanumeric, use word boundaries to avoid substring noise (e.g., "r").
        if skill_lower.replace(' ', '').isalnum():
            pattern = r"\b" + re.escape(skill_lower) + r"\b"
            if re.search(pattern, text_lower):
                found.append(skill)
        else:
            if skill_lower in text_lower:
                found.append(skill)
    return found

def calculate_tfidf_similarity(resume_text, job_desc):
    """Calculate TF-IDF based similarity score."""
    try:
        # Create TF-IDF vectorizer
        vectorizer = TfidfVectorizer()
        # Fit and transform both texts
        tfidf_matrix = vectorizer.fit_transform([resume_text, job_desc])
        # Calculate cosine similarity
        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])
        return round(similarity[0][0] * 100, 2)
    except:
        return 0.0

def calculate_match_percentage(matched_skills, job_skills):
    """Calculate match percentage based on skills matching."""
    if job_skills:
        return round((len(matched_skills) / len(job_skills)) * 100, 2)
    else:
        return 0.0

def generate_suggestions(missing_skills, matched_skills):
    """Generate improvement suggestions based on missing skills."""
    suggestions = []
    if missing_skills:
        suggestions.append(f"Consider adding {len(missing_skills)} missing skills to improve your match score.")
        if len(missing_skills) <= 3:
            suggestions.append("Focus on learning these key skills first.")
        else:
            suggestions.append("Prioritize the most in-demand skills from the missing list.")
    if matched_skills:
        suggestions.append(f"Your {len(matched_skills)} matched skills are a strong foundation.")
    if not missing_skills and not matched_skills:
        suggestions.append("Ensure your resume contains relevant technical skills.")
    return suggestions

def send_status_email(to_email, candidate_name, job_title, status, recruiter_name):
    sendgrid_api_key = os.getenv('SENDGRID_API_KEY')
    from_email = os.getenv('SENDGRID_FROM_EMAIL')
    if not sendgrid_api_key or not from_email:
        return False, 'SendGrid credentials not configured.'

    subject = f'Application {status} - {job_title}'
    if status == 'Selected':
        body = (
            f'Dear {candidate_name},\n\n'
            f'Congratulations! We are pleased to inform you that you have been selected for the role of {job_title}.\n'
            f'Our recruitment team will contact you shortly with the next steps.\n\n'
            f'Regards,\n'
            f'{recruiter_name}\n'
            f'Recruitment Team'
        )
    elif status == 'Rejected':
        body = (
            f'Dear {candidate_name},\n\n'
            f'Thank you for applying for the role of {job_title}. '
            f'After careful consideration, we regret to inform you that your application has not been selected at this time.\n'
            f'We appreciate your interest and encourage you to apply for future opportunities.\n\n'
            f'Regards,\n'
            f'{recruiter_name}\n'
            f'Recruitment Team'
        )
    else:
        body = (
            f'Dear {candidate_name},\n\n'
            f'Your application status for {job_title} has been updated to: {status}.\n\n'
            f'Regards,\n'
            f'{recruiter_name}\n'
            f'Recruitment Team'
        )

    try:
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email, "name": recruiter_name},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}]
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=data,
            headers={
                "Authorization": f"Bearer {sendgrid_api_key}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            if 200 <= resp.status < 300:
                return True, None
            return False, f"SendGrid error: HTTP {resp.status}"
    except Exception as exc:
        return False, str(exc)

@app.route('/')
@login_required
def index():
    """Role-based landing page after login."""
    if is_admin_user():
        return redirect(url_for('admin'))
    if current_user.role == 'recruiter':
        return redirect(url_for('recruiter_dashboard'))
    return redirect(url_for('dashboard'))
@app.route('/analyze', methods=['GET', 'POST'])
@login_required
@require_roles('candidate')
def analyze():
    """Analyze resume and job description."""
    if request.method == 'POST':
        file = request.files.get('resume')
        job_desc = request.form.get('job_desc', '').strip()
        
        # Validation
        if not file or file.filename == '':
            flash('Please upload a resume PDF.', 'error')
            return redirect(url_for('analyze'))
        if not job_desc:
            flash('Please enter a job description.', 'error')
            return redirect(url_for('analyze'))
        if not file.filename.lower().endswith('.pdf'):
            flash('Only PDF files are allowed.', 'error')
            return redirect(url_for('analyze'))
        
        # Secure filename and save
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Extract text from PDF
        resume_text = extract_text_from_pdf(file_path)
        if resume_text is None:
            flash('Unable to read the PDF. Please ensure it is a text-based PDF.', 'error')
            os.remove(file_path)
            return redirect(url_for('analyze'))
        
        # Get skills from resume and job desc
        resume_skills = get_skills_in_text(resume_text, SKILLS_LIST)
        job_skills = get_skills_in_text(job_desc, SKILLS_LIST)
        
        # Calculate matched and missing skills
        matched_skills = list(set(resume_skills) & set(job_skills))
        missing_skills = list(set(job_skills) - set(matched_skills))
        
        # Calculate match percentage using skills matching
        match_percentage = calculate_match_percentage(matched_skills, job_skills)

        # AI resume recommendations
        recommendations = []
        if missing_skills:
            recommendations.append(
                "Consider adding the following skills to improve your profile: "
                + ", ".join(missing_skills)
            )
        if match_percentage < 50:
            recommendations.append(
                "Your resume has low alignment with this job. Try emphasizing relevant projects or skills."
            )
        elif match_percentage < 75:
            recommendations.append(
                "Your resume partially matches the job requirements. Strengthening relevant experience may improve your chances."
            )
        else:
            recommendations.append(
                "Your resume strongly matches the job requirements. Consider highlighting key achievements."
            )
        
        # Generate suggestions
        suggestions = generate_suggestions(missing_skills, matched_skills)
        
        # Explanation
        explanation = (
            f"The match score is calculated by identifying skills from the job description "
            f"that are also present in the resume. "
            f"There are {len(job_skills)} skills in the job description. "
            f"{len(matched_skills)} of them match the resume, resulting in a {match_percentage}% match. "
            f"Missing skills are those in the job description but not found in the resume."
        )
        
        # Save to database
        analysis = ResumeAnalysis(
            user_id=current_user.id,
            resume_name=filename,
            job_description=job_desc,
            match_score=match_percentage,
            matched_skills=json.dumps(matched_skills),
            missing_skills=json.dumps(missing_skills),
            explanation=explanation
        )
        db.session.add(analysis)
        db.session.commit()
        
        # Clean up uploaded file
        os.remove(file_path)
        
        # Render results
        return render_template('results.html', 
                               match_percentage=match_percentage,
                               matched_skills=matched_skills,
                               missing_skills=missing_skills,
                               job_skills=job_skills,
                               explanation=explanation,
                               suggestions=suggestions,
                               recommendations=recommendations)
    
    return render_template('analyze.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """User signup page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        role = request.form.get('role', 'candidate').strip().lower()
        
        # Validation
        if not name or not email or not password:
            flash('All fields are required.', 'error')
            return redirect(url_for('signup'))
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('signup'))
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('signup'))
        if role not in ['candidate', 'recruiter']:
            role = 'candidate'
        
        # Check if user exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('signup'))
        
        # Create new user
        hashed_password = generate_password_hash(password)
        user = User(name=name, email=email, password=hashed_password, role=role)
        db.session.add(user)
        db.session.commit()
        
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        
        # Validation
        if not email or not password:
            flash('Email and password are required.', 'error')
            return redirect(url_for('login'))
        
        # Find user
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password.', 'error')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
@require_roles('candidate')
def dashboard():
    """User dashboard with past analyses."""
    analyses = ResumeAnalysis.query.filter_by(user_id=current_user.id).order_by(ResumeAnalysis.created_at.desc()).all()
    feedbacks = Feedback.query.all()
    return render_template('dashboard.html', analyses=analyses, feedbacks=feedbacks)

@app.route('/delete_analysis/<int:analysis_id>', methods=['POST'])
@login_required
@require_roles('candidate')
def delete_analysis(analysis_id):
    """Delete a past analysis."""
    analysis = ResumeAnalysis.query.filter_by(id=analysis_id, user_id=current_user.id).first()
    if analysis:
        db.session.delete(analysis)
        db.session.commit()
        flash('Analysis deleted successfully.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/recruiter_dashboard')
@login_required
@require_roles('recruiter')
def recruiter_dashboard():
    jobs = Job.query.filter_by(created_by=current_user.id).order_by(Job.created_at.desc()).all()
    total_jobs = len(jobs)
    applications = Application.query.join(Job).filter(Job.created_by == current_user.id).all()
    total_applications = len(applications)
    avg_score = 0
    top_score = 0
    if applications:
        avg_score = round(sum(app_item.match_score for app_item in applications) / len(applications), 2)
        top_score = round(max(app_item.match_score for app_item in applications), 2)
    status_counts = {
        'Applied': 0,
        'Shortlisted': 0,
        'Interview': 0,
        'Selected': 0,
        'Rejected': 0
    }
    for app_item in applications:
        if app_item.status in status_counts:
            status_counts[app_item.status] += 1
    return render_template(
        'recruiter_dashboard.html',
        jobs=jobs,
        total_jobs=total_jobs,
        total_applications=total_applications,
        avg_score=avg_score,
        top_score=top_score,
        status_counts=status_counts
    )

@app.route('/create_job', methods=['GET', 'POST'])
@login_required
@require_roles('recruiter')
def create_job():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        required_skills = request.form.get('required_skills', '').strip()
        experience_level = request.form.get('experience_level', '').strip()

        if not title or not description:
            flash('Job title and description are required.', 'error')
            return redirect(url_for('create_job'))

        job = Job(
            title=title,
            description=description,
            required_skills=required_skills,
            experience_level=experience_level,
            created_by=current_user.id
        )
        db.session.add(job)
        db.session.commit()
        flash('Job created successfully.', 'success')
        return redirect(url_for('recruiter_dashboard'))

    return render_template('create_job.html')

@app.route('/edit_job/<int:job_id>', methods=['GET', 'POST'])
@login_required
@require_roles('recruiter')
def edit_job(job_id):
    job = Job.query.filter_by(id=job_id, created_by=current_user.id).first_or_404()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        required_skills = request.form.get('required_skills', '').strip()
        experience_level = request.form.get('experience_level', '').strip()

        if not title or not description:
            flash('Job title and description are required.', 'error')
            return redirect(url_for('edit_job', job_id=job.id))

        job.title = title
        job.description = description
        job.required_skills = required_skills
        job.experience_level = experience_level
        db.session.commit()
        flash('Job updated successfully.', 'success')
        return redirect(url_for('recruiter_dashboard'))

    return render_template('edit_job.html', job=job)

@app.route('/delete_job/<int:job_id>', methods=['POST'])
@login_required
@require_roles('recruiter')
def delete_job(job_id):
    job = Job.query.filter_by(id=job_id, created_by=current_user.id).first_or_404()
    Application.query.filter_by(job_id=job.id).delete(synchronize_session=False)
    db.session.delete(job)
    db.session.commit()
    flash('Job deleted successfully.', 'success')
    return redirect(url_for('recruiter_dashboard'))

@app.route('/view_jobs')
@login_required
@require_roles('recruiter')
def view_jobs():
    return redirect(url_for('recruiter_dashboard'))

@app.route('/view_applicants/<int:job_id>')
@login_required
@require_roles('recruiter')
def view_applicants(job_id):
    job = Job.query.filter_by(id=job_id, created_by=current_user.id).first_or_404()
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()

    query = Application.query.filter_by(job_id=job.id)
    if status:
        query = query.filter_by(status=status)
    applications = query.order_by(Application.match_score.desc()).all()
    if search:
        applications = [
            app_item for app_item in applications
            if search.lower() in (app_item.matched_skills or '').lower()
        ]
    return render_template('view_applicants.html', job=job, applications=applications)

@app.route('/update_application_status', methods=['POST'])
@login_required
@require_roles('recruiter')
def update_application_status():
    app_id = request.form.get('application_id', '').strip()
    status = request.form.get('status', '').strip()
    if status not in ['Applied', 'Shortlisted', 'Interview', 'Selected', 'Rejected']:
        flash('Invalid status.', 'error')
        return redirect(url_for('recruiter_dashboard'))

    if not current_user.is_authenticated or current_user.role != 'recruiter':
        return redirect(url_for('dashboard'))

    application = Application.query.get(int(app_id)) if app_id.isdigit() else None
    if not application:
        flash('Application not found.', 'error')
        return redirect(url_for('recruiter_dashboard'))

    job = Job.query.filter_by(id=application.job_id, created_by=current_user.id).first()
    if not job:
        flash('You do not have permission to update this application.', 'error')
        return redirect(url_for('recruiter_dashboard'))

    candidate_email = application.candidate.email if application.candidate else None
    candidate_name = application.candidate.name if application.candidate else 'Candidate'

    if status == 'Rejected':
        if candidate_email:
            ok, err = send_status_email(
                candidate_email, candidate_name, application.job.title, 'Rejected', current_user.name
            )
            if ok:
                flash('Email sent successfully.', 'success')
            else:
                flash(f'Email not sent: {err}', 'error')
        db.session.delete(application)
        db.session.commit()
        flash('Application rejected and removed successfully', 'success')
        return redirect(request.referrer or url_for('dashboard'))

    application.status = status
    db.session.commit()

    if status == 'Selected' and candidate_email:
        ok, err = send_status_email(
            candidate_email, candidate_name, application.job.title, 'Selected', current_user.name
        )
        if ok:
            flash('Email sent successfully.', 'success')
        else:
            flash(f'Email not sent: {err}', 'error')

    flash('Application status updated.', 'success')
    return redirect(url_for('view_applicants', job_id=application.job_id))

@app.route('/add_note/<int:app_id>', methods=['POST'])
@login_required
def add_note(app_id):
    if current_user.role != 'recruiter':
        return redirect(url_for('dashboard'))

    application = Application.query.get_or_404(app_id)
    job = Job.query.filter_by(id=application.job_id, created_by=current_user.id).first()
    if not job:
        flash('You do not have permission to update this application.', 'error')
        return redirect(url_for('recruiter_dashboard'))

    application.notes = request.form.get('note', '').strip()
    db.session.commit()
    flash('Note saved successfully', 'success')
    return redirect(request.referrer or url_for('recruiter_dashboard'))

@app.route('/resume/<path:filename>')
@login_required
def view_resume(filename):
    if current_user.role not in ['recruiter', 'admin']:
        return redirect(url_for('dashboard'))
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(file_path):
        flash('Resume file not found. It may have been cleaned up from the server.', 'error')
        return redirect(request.referrer or url_for('recruiter_dashboard'))
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/auto_shortlist/<int:job_id>', methods=['POST'])
@login_required
@require_roles('recruiter')
def auto_shortlist(job_id):
    job = Job.query.filter_by(id=job_id, created_by=current_user.id).first_or_404()
    applications = Application.query.filter_by(job_id=job.id).order_by(Application.match_score.desc()).all()
    if not applications:
        flash('No applicants found', 'error')
        return redirect(request.referrer or url_for('recruiter_dashboard'))

    top_count = max(1, int(len(applications) * 0.1))
    for app_item in applications[:top_count]:
        app_item.status = 'Shortlisted'
    db.session.commit()
    flash(f'Top {top_count} candidates shortlisted automatically', 'success')
    return redirect(request.referrer or url_for('view_applicants', job_id=job.id))

@app.route('/export_csv/<int:job_id>')
@login_required
@require_roles('recruiter')
def export_csv(job_id):
    job = Job.query.filter_by(id=job_id, created_by=current_user.id).first_or_404()
    applications = Application.query.filter_by(job_id=job.id).all()

    rows = [
        ['Candidate', 'Match Score', 'Status', 'Skills']
    ]
    for app_item in applications:
        candidate_name = app_item.candidate.name if app_item.candidate else 'Unknown'
        rows.append([
            candidate_name,
            app_item.match_score,
            app_item.status,
            app_item.matched_skills or ''
        ])

    def generate():
        for row in rows:
            yield ",".join(map(str, row)) + "\n"

    return Response(
        generate(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=applicants.csv'}
    )

@app.route('/jobs')
@login_required
@require_roles('candidate')
def jobs():
    all_jobs = Job.query.order_by(Job.created_at.desc()).all()
    applications = Application.query.filter_by(candidate_id=current_user.id).all()
    app_map = {app_item.job_id: app_item for app_item in applications}
    return render_template('jobs.html', jobs=all_jobs, app_map=app_map)

@app.route('/apply_job/<int:job_id>', methods=['GET', 'POST'])
@login_required
@require_roles('candidate')
def apply_job(job_id):
    job = Job.query.get_or_404(job_id)
    existing = Application.query.filter_by(job_id=job.id, candidate_id=current_user.id).first()
    if existing:
        flash('You have already applied to this job.', 'error')
        return redirect(url_for('jobs'))

    if request.method == 'POST':
        file = request.files.get('resume')
        if not file or file.filename == '':
            flash('Please upload a resume PDF.', 'error')
            return redirect(url_for('apply_job', job_id=job.id))
        if not file.filename.lower().endswith('.pdf'):
            flash('Only PDF files are allowed.', 'error')
            return redirect(url_for('apply_job', job_id=job.id))

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        resume_text = extract_text_from_pdf(file_path)
        if resume_text is None:
            flash('Unable to read the PDF. Please ensure it is a text-based PDF.', 'error')
            os.remove(file_path)
            return redirect(url_for('apply_job', job_id=job.id))

        required_skills_list = parse_required_skills(job.required_skills)
        job_desc_skills = get_skills_in_text(job.description, SKILLS_LIST)
        job_skills = list(set(required_skills_list + job_desc_skills))

        combined_skills = list(set(SKILLS_LIST + required_skills_list))
        resume_skills = get_skills_in_text(resume_text, combined_skills)
        matched_skills = list(set(resume_skills) & set(job_skills))

        missing_skills = list(set(job_skills) - set(matched_skills))

        match_percentage = calculate_match_percentage(matched_skills, job_skills)

        candidate_email = extract_email(resume_text)
        candidate_name = extract_name(resume_text)
        matched_skills_str = ",".join(matched_skills)
        missing_skills_str = ",".join(missing_skills)
        if match_percentage >= 75:
            role_fit = "Good Fit"
        elif match_percentage >= 50:
            role_fit = "Potential Fit"
        else:
            role_fit = "Low Fit"

        application = Application(
            job_id=job.id,
            candidate_id=current_user.id,
            resume_name=filename,
            match_score=match_percentage,
            status='Applied',
            parsed_name=candidate_name,
            parsed_email=candidate_email,
            matched_skills=matched_skills_str,
            missing_skills=missing_skills_str,
            role_fit=role_fit
        )
        db.session.add(application)
        db.session.commit()

        flash(f'Application submitted. Match score: {match_percentage}%.', 'success')
        return redirect(url_for('acknowledgement'))

    return render_template('apply_job.html', job=job)

@app.route('/my_applications')
@login_required
@require_roles('candidate')
def my_applications():
    applications = Application.query.filter_by(candidate_id=current_user.id).order_by(Application.created_at.desc()).all()
    return render_template('my_applications.html', applications=applications)

@app.route('/acknowledgement')
@login_required
def acknowledgement():
    return render_template('acknowledgement.html')

@app.route('/feedback', methods=['GET', 'POST'])
@login_required
def feedback():
    if request.method == 'POST':
        rating = request.form.get('rating')
        comment = request.form.get('comment', '').strip()

        rating_val = int(rating) if rating and rating.isdigit() else None

        new_feedback = Feedback(
            user_id=current_user.id,
            rating=rating_val,
            comment=comment
        )

        db.session.add(new_feedback)
        db.session.commit()

        flash('Thank you for your feedback!', 'success')
        return redirect(url_for('my_applications'))

    return render_template('feedback.html')

def ensure_role_column():
    """Add role column to existing user table if missing for backward compatibility."""
    try:
        result = db.session.execute(text("PRAGMA table_info(user)")).fetchall()
        columns = [row[1] for row in result]
        if 'role' not in columns:
            db.session.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'candidate'"))
            db.session.commit()
        db.session.execute(text("UPDATE user SET role='candidate' WHERE role IS NULL OR role=''"))
        db.session.commit()
    except Exception:
        db.session.rollback()

def ensure_application_parsed_columns():
    """Add parsed_name, parsed_email, matched_skills, missing_skills, notes, role_fit columns if missing."""
    try:
        result = db.session.execute(text("PRAGMA table_info(application)")).fetchall()
        columns = [row[1] for row in result]
        if 'parsed_name' not in columns:
            db.session.execute(text("ALTER TABLE application ADD COLUMN parsed_name VARCHAR(120)"))
        if 'parsed_email' not in columns:
            db.session.execute(text("ALTER TABLE application ADD COLUMN parsed_email VARCHAR(120)"))
        if 'matched_skills' not in columns:
            db.session.execute(text("ALTER TABLE application ADD COLUMN matched_skills TEXT"))
        if 'missing_skills' not in columns:
            db.session.execute(text("ALTER TABLE application ADD COLUMN missing_skills TEXT"))
        if 'notes' not in columns:
            db.session.execute(text("ALTER TABLE application ADD COLUMN notes TEXT"))
        if 'role_fit' not in columns:
            db.session.execute(text("ALTER TABLE application ADD COLUMN role_fit VARCHAR(50)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

# Create database tables
with app.app_context():
    db.create_all()
    ensure_role_column()
    ensure_application_parsed_columns()

@app.route('/admin')
@login_required
def admin():
    """Admin page to view all users"""
    if not is_admin_user():
        flash('You do not have permission to access this page.', 'error')
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    analyses = ResumeAnalysis.query.all()
    jobs = Job.query.all()
    applications = Application.query.order_by(Application.created_at.desc()).all()

    status_counts = {
        'Applied': 0,
        'Shortlisted': 0,
        'Interview': 0,
        'Selected': 0,
        'Rejected': 0
    }
    for app_item in applications:
        if app_item.status in status_counts:
            status_counts[app_item.status] += 1

    feedbacks = Feedback.query.all()

    return render_template(
        'admin.html',
        users=users,
        analyses=analyses,
        jobs=jobs,
        applications=applications,
        feedbacks=feedbacks,
        status_counts=status_counts
    )

@app.route('/delete_feedback/<int:feedback_id>', methods=['POST'])
@login_required
def delete_feedback(feedback_id):
    if not is_admin_user():
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('dashboard'))

    feedback = Feedback.query.get_or_404(feedback_id)
    db.session.delete(feedback)
    db.session.commit()
    flash('Feedback deleted successfully.', 'success')
    return redirect(request.referrer or url_for('admin'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not is_admin_user():
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('dashboard'))

    user = User.query.get_or_404(user_id)

    # Remove dependent data to avoid FK issues
    db.session.query(ResumeAnalysis).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.query(Application).filter_by(candidate_id=user.id).delete(synchronize_session=False)

    recruiter_jobs = Job.query.filter_by(created_by=user.id).all()
    recruiter_job_ids = [job.id for job in recruiter_jobs]
    if recruiter_job_ids:
        db.session.query(Application).filter(Application.job_id.in_(recruiter_job_ids)).delete(synchronize_session=False)
        db.session.query(Job).filter(Job.id.in_(recruiter_job_ids)).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()

    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
