from flask import Flask, render_template, session, redirect, url_for, flash, request, jsonify, send_file
import subprocess
import re
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import csv
from datetime import datetime,timedelta
app = Flask(__name__)

# Provide a default database URI (required for SQLAlchemy to work)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///default.db'  # This is needed, even if you are using binds.

# Define multiple database bindings
app.config['SQLALCHEMY_BINDS'] = {
    'admin_db': 'sqlite:///admin.db',
    'student_db': 'sqlite:///students.db'
}

app.config['SECRET_KEY'] = 'supersecretkey'  # Needed for flash messages
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# Admin Table (Stored in admin.db)
class Admin(db.Model):
    __bind_key__ = 'admin_db'
    id = db.Column(db.Integer, primary_key=True)
    idname = db.Column(db.String(50), nullable=False, unique=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password = db.Column(db.String(100), nullable=False)
    session_active = db.Column(db.Boolean, default=False) 

# Update the Student model
class Student(db.Model):
    __bind_key__ = 'student_db'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False, unique=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password = db.Column(db.String(100), nullable=False)
    is_logged_in = db.Column(db.Boolean, default=False)
    login_time = db.Column(db.DateTime)  # New column
    last_active_time = db.Column(db.DateTime)  # New column
# Correct usage of db.create_all()
with app.app_context():
    db.create_all()  # This will create tables for all bound databases

# Function to get connected WiFi BSSID
def get_wifi_bssid():
    try:
        import platform
        system = platform.system()

        if system == "Windows":
            result = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True)
            match = re.search(r'BSSID\s*:\s*([0-9A-Fa-f:-]+)', result.stdout)
        else:  # Linux / macOS
            result = subprocess.run(["iwconfig"], capture_output=True, text=True)
            match = re.search(r'Access Point: ([0-9A-Fa-f:]+)', result.stdout)

        return match.group(1) if match else "BSSID not found"
    except Exception as e:
        return str(e)


@app.route('/')
def index():
    bssid1 = get_wifi_bssid()
    return render_template('index.html', bssid1=bssid1)


# Admin Registration Route
@app.route('/register_admin', methods=['GET', 'POST'])
def register_admin():
    if request.method == 'POST':
        idname = request.form['idname']
        username = request.form['username']
        password = request.form['password']
        secret_key = request.form['secret_key']

        if secret_key != "69420":
            flash("Invalid secret key! Registration failed.", "danger")
            return redirect(url_for('register_admin'))

        # Check if admin already exists
        with app.app_context():
            existing_admin = Admin.query.filter(
                (Admin.idname == idname) | (Admin.username == username)
            ).first()

            if existing_admin:
                flash("Admin ID or username already exists!", "danger")
                return redirect(url_for('register_admin'))

            # Hash the password
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

            # Save admin to database
            new_admin = Admin(idname=idname, username=username, password=hashed_password)
            db.session.add(new_admin)
            db.session.commit()

        flash("Admin registered successfully!", "success")
        return redirect(url_for('login_admin'))

    return render_template('register-admin.html')


# Admin Login Route
@app.route('/login_admin', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        admin = Admin.query.filter_by(username=username).first()
        if admin and bcrypt.check_password_hash(admin.password, password):
            session['admin_id'] = admin.id
            flash("Login successful!", "success")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid username or password!", "danger")

    return render_template('login-admin.html')

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        flash("Please log in first!", "warning")
        return redirect(url_for('login_admin'))

    admin = Admin.query.filter_by(id=session['admin_id']).first()
    students = Student.query.filter_by(is_logged_in=True).order_by(Student.student_id).all()
    
    students_with_status = []
    current_time = datetime.now()
    for student in students:
        status = 'Inactive'
        active_time = timedelta(0)
        
        if student.login_time:
            if student.last_active_time and (current_time - student.last_active_time) <= timedelta(minutes=5):
                status = 'Active'
                active_time = current_time - student.login_time
            else:
                active_time = (student.last_active_time - student.login_time) if student.last_active_time else timedelta(0)
            
            total_seconds = int(active_time.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            active_time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
        else:
            active_time_str = "00:00:00"
        
        students_with_status.append({
            'student_id': student.student_id,
            'username': student.username,
            'status': status,
            'active_time': active_time_str
        })

    return render_template('admin-dashboard.html', students_present=students_with_status, session_active=admin.session_active)
@app.route('/start_session', methods=['POST'])
def start_session():
    if 'admin_id' in session:
        admin = Admin.query.filter_by(id=session['admin_id']).first()
        admin.session_active = True
        db.session.commit()
        return jsonify({"message": "Session started successfully!"})
    return jsonify({"error": "Unauthorized"}), 403

# Update the end_session route
@app.route('/end_session', methods=['POST'])
def end_session():
    if 'admin_id' in session:
        admin = Admin.query.filter_by(id=session['admin_id']).first()
        admin.session_active = False

        # Reset all student sessions and times
        Student.query.update({
            "is_logged_in": False,
            "login_time": None,
            "last_active_time": None
        })
        db.session.commit()

        return jsonify({"message": "Session ended and database reset!"})
    return jsonify({"error": "Unauthorized"}), 403
# Modify the /active_students route
@app.route('/active_students')
def active_students():
    students = Student.query.filter_by(is_logged_in=True).order_by(Student.student_id).all()
    student_data = []
    current_time = datetime.now()
    
    for student in students:
        status = 'Inactive'
        active_time = timedelta(0)
        
        if student.login_time:
            if student.last_active_time and (current_time - student.last_active_time) <= timedelta(minutes=5):
                status = 'Active'
                active_time = current_time - student.login_time
            else:
                active_time = (student.last_active_time - student.login_time) if student.last_active_time else timedelta(0)
            
            total_seconds = int(active_time.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            active_time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
        else:
            active_time_str = "00:00:00"
        
        student_data.append({
            "student_id": student.student_id,
            "username": student.username,
            "status": status,
            "active_time": active_time_str
        })
    
    return jsonify(student_data)

@app.route('/download_attendance')
def download_attendance():
    students = Student.query.filter_by(is_logged_in=True).order_by(Student.student_id).all()
    file_path = "attendance.csv"
    
    with open(file_path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["Student ID", "Username"])
        for student in students:
            writer.writerow([student.student_id, student.username])
    
    return send_file(file_path, as_attachment=True)

@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        student_id = request.form['student_id']
        username = request.form['username']
        password = request.form['password']

        # Check if student already exists
        with app.app_context():
            existing_student = Student.query.filter(
                (Student.student_id == student_id) | (Student.username == username)
            ).first()

            if existing_student:
                flash("Student ID or username already exists!", "danger")
                return redirect(url_for('register_student'))

            # Hash password
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

            # Save student to database
            new_student = Student(student_id=student_id, username=username, password=hashed_password)
            db.session.add(new_student)
            db.session.commit()

        flash("Student registered successfully!", "success")
        return redirect(url_for('login_student'))

    return render_template('register-student.html')


@app.route('/login_student', methods=['GET', 'POST'])
def login_student():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        student = Student.query.filter_by(username=username).first()
        if student and bcrypt.check_password_hash(student.password, password):
            session['student_id'] = student.student_id
            student.is_logged_in = True
            student.login_time = datetime.now()
            student.last_active_time = datetime.now()
            db.session.commit()
            flash("Login successful!", "success")
            return redirect(url_for('student_dashboard'))
        else:
            flash("Invalid username or password!", "danger")

    return render_template('login-student.html')

# Student Dashboard (Protected Route)
@app.route('/student_dashboard')
def student_dashboard():
    if 'student_id' in session:
        student = Student.query.filter_by(student_id=session['student_id']).first()
        return render_template('student-dashboard.html', student=student)

    flash("Please log in first!", "warning")
    return redirect(url_for('login_student'))

@app.route('/logout')
def logout():
    if 'student_id' in session:
        student = Student.query.filter_by(student_id=session['student_id']).first()
        if student:
            student.is_logged_in = False
            student.login_time = None
            student.last_active_time = None
            db.session.commit()
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect(url_for('login_student'))

# Add a new route for activity updates
@app.route('/update_activity', methods=['POST'])
def update_activity():
    if 'student_id' in session:
        student = Student.query.filter_by(student_id=session['student_id']).first()
        if student and student.is_logged_in:
            student.last_active_time = datetime.now()
            db.session.commit()
            return jsonify({"success": True})
    return jsonify({"success": False}), 401


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
