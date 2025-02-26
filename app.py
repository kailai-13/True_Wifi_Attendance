from flask import Flask, render_template, session, redirect, url_for, flash, request, jsonify, send_file
import subprocess
import re
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import csv
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import numpy as np
import cv2
import base64
import os

# Create directory for storing face images if it doesn't exist
os.makedirs('face_data', exist_ok=True)
face_detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
face_recognizer = cv2.face.LBPHFaceRecognizer_create()
# Generate a key (do this once and store securely)
KEY = Fernet.generate_key()
cipher_suite = Fernet(KEY)
app = Flask(__name__)

# Provide a default database URI (required for SQLAlchemy to work)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///default.db'

# Define multiple database bindings
app.config['SQLALCHEMY_BINDS'] = {
    'admin_db': 'sqlite:///admin.db',
    'student_db': 'sqlite:///students.db',
}

app.config['SECRET_KEY'] = 'supersecretkey'
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

# Update the Student model with face_encoding field
class Student(db.Model):
    __bind_key__ = 'student_db'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False, unique=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password = db.Column(db.String(100), nullable=False)
    face_encoding = db.Column(db.Text)  # Store face encoding as base64 string
    
    is_logged_in = db.Column(db.Boolean, default=False)
    login_time = db.Column(db.DateTime)
    last_active_time = db.Column(db.DateTime)

class AttendanceRecord(db.Model):
    __bind_key__ = 'student_db'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), db.ForeignKey('student.student_id'))
    login_time = db.Column(db.DateTime)
    logout_time = db.Column(db.DateTime)
    active_duration = db.Column(db.Float)  # Duration in minutes

# Initialize face recognition
face_detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
face_recognizer = cv2.face.LBPHFaceRecognizer_create()

# Create database tables
with app.app_context():
    db.create_all()
    # Train face recognizer with existing faces
    try:
        face_recognizer.read('face_model.yml')
    except:
        pass  # No model yet

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
def retrain_face_recognizer():
    """Retrain the face recognition model with all registered students"""
    students = Student.query.all()
    faces = []
    labels = []

    for student in students:
        if student.face_encoding:
            try:
                # Decode stored face image
                face_bytes = base64.b64decode(student.face_encoding)
                np_arr = np.frombuffer(face_bytes, np.uint8)
                face_img = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                
                faces.append(face_img)
                labels.append(student.id)  # Use database ID as label
            except Exception as e:
                print(f"Error processing face for student {student.id}: {e}")

    if len(faces) > 0:
        face_recognizer.train(faces, np.array(labels, dtype=np.int32))
        face_recognizer.save('face_model.yml')
        print("Face recognizer retrained successfully")
    else:
        print("No faces found for training")

# Initialize or load face recognizer on startup
with app.app_context():
    db.create_all()
    try:
        if os.path.exists('face_model.yml'):
            face_recognizer.read('face_model.yml')
        else:
            retrain_face_recognizer()
    except Exception as e:
        print(f"Error initializing face recognizer: {e}")
@app.route('/')
def index():
    bssid1 = get_wifi_bssid()
    return render_template('index.html', bssid1=bssid1)

# Admin Registration and Login routes remain unchanged
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

        with app.app_context():
            existing_admin = Admin.query.filter(
                (Admin.idname == idname) | (Admin.username == username)
            ).first()

            if existing_admin:
                flash("Admin ID or username already exists!", "danger")
                return redirect(url_for('register_admin'))

            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            new_admin = Admin(idname=idname, username=username, password=hashed_password)
            db.session.add(new_admin)
            db.session.commit()

        flash("Admin registered successfully!", "success")
        return redirect(url_for('login_admin'))

    return render_template('register-admin.html')

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

# Admin dashboard and related routes remain largely unchanged
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

@app.route('/end_session', methods=['POST'])
def end_session():
    if 'admin_id' in session:
        admin = Admin.query.filter_by(id=session['admin_id']).first()
        admin.session_active = False

        logged_in_students = Student.query.filter_by(is_logged_in=True).all()
        for student in logged_in_students:
            if student.login_time and student.last_active_time:
                duration = (student.last_active_time - student.login_time).total_seconds() / 60
                record = AttendanceRecord(
                    student_id=student.student_id,
                    login_time=student.login_time,
                    logout_time=student.last_active_time,
                    active_duration=duration
                )
                db.session.add(record)

            student.is_logged_in = False
            student.login_time = None
            student.last_active_time = None

        db.session.commit()
        return jsonify({"message": "Session ended and attendance records saved!"})
    return jsonify({"error": "Unauthorized"}), 403

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
        writer.writerow(["Student ID", "Username", "Login Time", "Last Active Time", "Active Duration (minutes)"])
        
        for student in students:
            login_time = student.login_time.strftime("%Y-%m-%d %H:%M:%S") if student.login_time else "N/A"
            last_active_time = student.last_active_time.strftime("%Y-%m-%d %H:%M:%S") if student.last_active_time else "N/A"
            
            if student.login_time and student.last_active_time:
                active_duration = (student.last_active_time - student.login_time).total_seconds() / 60  # Convert to minutes
                active_duration = round(active_duration, 2)
            else:
                active_duration = "N/A"

            writer.writerow([student.student_id, student.username, login_time, last_active_time, active_duration])
    
    return send_file(file_path, as_attachment=True)

# Face recognition helper functions
def process_face_image(image_data):
    """Process base64 image data and extract face encoding"""
    try:
        # Decode base64 image
        image_data = image_data.split(',')[1]
        image_bytes = base64.b64decode(image_data)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        # Convert to grayscale for face detection
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = face_detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        
        if len(faces) == 0:
            return None, "No face detected"
        
        if len(faces) > 1:
            return None, "Multiple faces detected"
        
        # Extract the face region
        x, y, w, h = faces[0]
        face_img = gray[y:y+h, x:x+w]
        
        # Resize to standard size
        face_img = cv2.resize(face_img, (100, 100))
        
        # Encode the face image to base64 for storage
        _, buffer = cv2.imencode('.jpg', face_img)
        face_encoded = base64.b64encode(buffer).decode('utf-8')
        
        # Save face image for training
        return face_encoded, "Success"
    except Exception as e:
        return None, str(e)

def verify_face(student_id, image_data):
    """Verify if the captured face matches the stored face"""
    try:
        # Load pre-trained model
        face_recognizer.read('face_model.yml')

        # Get student by student_id
        student = Student.query.filter_by(student_id=student_id).first()
        if not student or not student.face_encoding:
            return False, "Student not found or no face data"

        # Process submitted image
        image_data = image_data.split(',')[1]
        image_bytes = base64.b64decode(image_data)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Detect face
        faces = face_detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) != 1:
            return False, "No or multiple faces detected"

        # Process face
        x, y, w, h = faces[0]
        face_img = gray[y:y+h, x:x+w]
        face_img = cv2.resize(face_img, (100, 100))

        # Predict using pre-trained model
        label, confidence = face_recognizer.predict(face_img)

        # Verify prediction matches student ID
        if label == student.id and confidence < 70:
            return True, "Face verified"
        else:
            return False, f"Verification failed (confidence: {confidence})"

    except Exception as e:
        return False, str(e)
# Modified student registration to capture face
@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        student_id = request.form['student_id']
        username = request.form['username']
        password = request.form['password']
        face_image = request.form['face_image']
        
        # Check if student already exists
        existing_student = Student.query.filter(
            (Student.student_id == student_id) | (Student.username == username)
        ).first()

        if existing_student:
            flash("Student ID or username already exists!", "danger")
            return redirect(url_for('register_student'))
        
        # Process face image
        face_encoding, message = process_face_image(face_image)
        if not face_encoding:
            flash(f"Face registration failed: {message}", "danger")
            return redirect(url_for('register_student'))

        # Hash password
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Save student with face data
        new_student = Student(
            student_id=student_id,
            username=username,
            password=hashed_password,
            face_encoding=face_encoding
        )
        db.session.add(new_student)
        db.session.commit()
        retrain_face_recognizer()

        flash("Student registered successfully!", "success")
        return redirect(url_for('login_student'))

    return render_template('register-student.html')

# Modified student login to verify face
@app.route('/login_student', methods=['GET', 'POST'])
def login_student():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        face_image = request.form.get('face_image')

        student = Student.query.filter_by(username=username).first()
        if not student:
            flash("Invalid username or password!", "danger")
            return redirect(url_for('login_student'))
            
        if not bcrypt.check_password_hash(student.password, password):
            flash("Invalid username or password!", "danger")
            return redirect(url_for('login_student'))
            
        # Verify face
        if not face_image:
            flash("Face verification required!", "danger")
            return redirect(url_for('login_student'))
            
        is_verified, message = verify_face(student.student_id, face_image)
        if not is_verified:
            flash(f"Face verification failed: {message}", "danger")
            return redirect(url_for('login_student'))

        # Login successful
        session['student_id'] = student.student_id
        student.is_logged_in = True

        # Set login_time only if it's not already set (first login of session)
        if not student.login_time:
            student.login_time = datetime.now()

        # Always update last_active_time on login
        student.last_active_time = datetime.now()

        db.session.commit()
        flash("Login successful!", "success")
        return redirect(url_for('student_dashboard'))

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
        if student and student.is_logged_in:
            # Create attendance record
            if student.login_time and student.last_active_time:
                duration = (student.last_active_time - student.login_time).total_seconds() / 60
                record = AttendanceRecord(
                    student_id=student.student_id,
                    login_time=student.login_time,
                    logout_time=student.last_active_time,
                    active_duration=duration
                )
                db.session.add(record)
            
            # Clear session data
            student.is_logged_in = False
            student.login_time = None
            student.last_active_time = None
            db.session.commit()
        
        session.clear()
        flash("Logged out successfully!", "success")
    return redirect(url_for('login_student'))

@app.route('/update_activity', methods=['POST'])
def update_activity():
    if 'student_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    student = Student.query.filter_by(student_id=session['student_id']).first()
    if student and student.is_logged_in:
        if not student.login_time:
            student.login_time = datetime.now()
        student.last_active_time = datetime.now()
        db.session.commit()
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "Student not logged in"}), 400

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)