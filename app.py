from flask import Flask, render_template, session, redirect, url_for, flash, request, jsonify, send_file
import subprocess
import re
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import csv
from datetime import datetime, timedelta
import numpy as np
import cv2
import base64
import os
from ultralytics import YOLO
from flask_session import Session

# Create directory for storing face images if it doesn't exist
os.makedirs('face_data', exist_ok=True)

# Load YOLOv8 face detection model
face_model = YOLO('yolov8n.pt')  # Ensure you have the YOLOv8 face model

app = Flask(__name__)

# Provide a default database URI (required for SQLAlchemy to work)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///default.db'

# Define multiple database bindings
app.config['SQLALCHEMY_BINDS'] = {
    'admin_db': 'sqlite:///admin.db',
    'student_db': 'sqlite:///students.db',
    'room_db': 'sqlite:///rooms.db'  # New database for room management
}

app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)
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
    current_bssid = db.Column(db.String(100))  # Store admin's current BSSID

# Room Table (Stored in room_db)
class Room(db.Model):
    __bind_key__ = 'room_db'
    id = db.Column(db.Integer, primary_key=True)
    room_code = db.Column(db.String(50), nullable=False, unique=True)
    admin_id = db.Column(db.Integer, nullable=False)  # ID of admin who created the room
    created_at = db.Column(db.DateTime, default=datetime.now)
    active = db.Column(db.Boolean, default=True)
    bssid = db.Column(db.String(100))  # Store the BSSID when room was created

# Update the Student model with face_encoding field and room info
class Student(db.Model):
    __bind_key__ = 'student_db'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False, unique=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password = db.Column(db.String(100), nullable=False)
    face_encoding = db.Column(db.Text)  # Store face encoding as base64 string
    current_room = db.Column(db.String(50))  # Store current room code
    
    is_logged_in = db.Column(db.Boolean, default=False)
    login_time = db.Column(db.DateTime)
    last_active_time = db.Column(db.DateTime)

class AttendanceRecord(db.Model):
    __bind_key__ = 'student_db'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), db.ForeignKey('student.student_id'))
    room_code = db.Column(db.String(50))  # Added room code to attendance record
    login_time = db.Column(db.DateTime)
    logout_time = db.Column(db.DateTime)
    active_duration = db.Column(db.Float)  # Duration in minutes

# Create database tables
with app.app_context():
    db.create_all()

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

def process_face_image(image_data):
    """Process base64 image data and extract face encoding using YOLOv8"""
    try:
        # Decode base64 image
        image_data = image_data.split(',')[1]
        image_bytes = base64.b64decode(image_data)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        # Detect faces using YOLOv8
        results = face_model(img)
        
        if len(results[0].boxes) == 0:
            return None, "No face detected"
        
        if len(results[0].boxes) > 1:
            return None, "Multiple faces detected"
        
        # Extract the face region
        x1, y1, x2, y2 = results[0].boxes.xyxy[0].tolist()
        face_img = img[int(y1):int(y2), int(x1):int(x2)]
        
        # Resize to standard size
        face_img = cv2.resize(face_img, (100, 100))
        
        # Encode the face image to base64 for storage
        _, buffer = cv2.imencode('.jpg', face_img)
        face_encoded = base64.b64encode(buffer).decode('utf-8')
        
        return face_encoded, "Success"
    except Exception as e:
        return None, str(e)

def verify_face(student_id, image_data):
    """Verify if the captured face matches the stored face using YOLOv8"""
    try:
        # Get student by student_id
        student = Student.query.filter_by(student_id=student_id).first()
        if not student or not student.face_encoding:
            return False, "Student not found or no face data"

        # Process submitted image
        image_data = image_data.split(',')[1]
        image_bytes = base64.b64decode(image_data)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        # Detect face using YOLOv8
        results = face_model(img)
        if len(results[0].boxes) != 1:
            return False, "No or multiple faces detected"

        # Extract the face region
        x1, y1, x2, y2 = results[0].boxes.xyxy[0].tolist()
        face_img = img[int(y1):int(y2), int(x1):int(x2)]
        face_img = cv2.resize(face_img, (100, 100))

        # Compare with stored face
        stored_face_bytes = base64.b64decode(student.face_encoding)
        stored_face_arr = np.frombuffer(stored_face_bytes, np.uint8)
        stored_face_img = cv2.imdecode(stored_face_arr, cv2.IMREAD_COLOR)

        # Simple comparison using Mean Squared Error (MSE)
        mse = np.mean((face_img - stored_face_img) ** 2)
        if mse < 1000:  # Adjust threshold as needed
            return True, "Face verified"
        else:
            return False, f"Verification failed (MSE: {mse})"

    except Exception as e:
        return False, str(e)

# Main index route
@app.route('/')
def index():
    bssid = get_wifi_bssid()
    return render_template('index.html', bssid=bssid)

# Admin registration
@app.route('/register_admin', methods=['GET', 'POST'])
def register_admin():
    if request.method == 'POST':
        idname = request.form.get('idname')
        username = request.form.get('username')
        password = request.form.get('password')
        secret_key = request.form.get('secret_key')
        
        # Check if the secret key is correct (hardcoded for simplicity)
        #if secret_key != 69420:  # You'd want a more secure approach in production
            #flash("Invalid secret key")
            #return redirect(url_for('register_admin'))
            
        existing_admin = Admin.query.filter_by(username=username).first()
        if existing_admin:
            flash("Username already exists")
            return redirect(url_for('register_admin'))
            
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_admin = Admin(idname=idname, username=username, password=hashed_password)
        
        db.session.add(new_admin)
        db.session.commit()
        
        flash("Registration successful")
        return redirect(url_for('login_admin'))
        
    return render_template('register_admin.html')

# Admin login
@app.route('/login_admin', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and bcrypt.check_password_hash(admin.password, password):
            session['admin_id'] = admin.id
            session['admin_username'] = admin.username
            
            # Save current BSSID
            current_bssid = get_wifi_bssid()
            admin.current_bssid = current_bssid
            db.session.commit()
            
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid username or password")
            
    return render_template('login_admin.html')

# Admin dashboard
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        flash("Please login first")
        return redirect(url_for('login_admin'))
        
    # Get students who are currently logged in
    students_present = []
    active_students = Student.query.filter_by(is_logged_in=True).all()
    
    for student in active_students:
        # Calculate active time
        if student.login_time:
            active_duration = datetime.now() - student.login_time
            hours, remainder = divmod(active_duration.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            active_time = f"{hours:02}:{minutes:02}:{seconds:02}"
        else:
            active_time = "00:00:00"
        
        # Check if student is active within last 2 minutes
        status = "Active"
        if student.last_active_time and (datetime.now() - student.last_active_time).seconds > 120:
            status = "Inactive"
            
        students_present.append({
            'student_id': student.student_id,
            'username': student.username,
            'status': status,
            'active_time': active_time,
            'room': student.current_room
        })
        
    # Get all rooms created by this admin
    admin_id = session.get('admin_id')
    rooms = Room.query.filter_by(admin_id=admin_id).all()
    
    return render_template('admin_dashboard.html', students_present=students_present, rooms=rooms)

# Create a new room
# ... existing imports and config ...

@app.route('/create_room', methods=['POST'])
def create_room():
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
        
    room_code = request.form.get('room_code')
    
    # Check if room code already exists
    existing_room = Room.query.filter_by(room_code=room_code).first()
    if existing_room:
        return jsonify({'success': False, 'message': 'Room code already exists'})
    
    # Get admin's current BSSID
    admin_id = session.get('admin_id')
    admin = Admin.query.get(admin_id)
    
    # Create new room
    new_room = Room(
        room_code=room_code,
        admin_id=admin_id,
        bssid=admin.current_bssid,
        active=True
    )
    
    db.session.add(new_room)
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Room {room_code} created successfully'})

@app.route('/close_room/<room_code>', methods=['POST'])
def close_room(room_code):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
    
    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()
    
    if not room:
        return jsonify({'success': False, 'message': 'Room not found'})
    
    # Set room as inactive
    room.active = False
    
    # Log out all students in the room
    students_in_room = Student.query.filter_by(current_room=room_code, is_logged_in=True).all()
    for student in students_in_room:
        # Create attendance record
        if student.login_time:
            active_duration = (datetime.now() - student.login_time).total_seconds() / 60
            attendance = AttendanceRecord(
                student_id=student.student_id,
                room_code=room_code,
                login_time=student.login_time,
                logout_time=datetime.utcnow(),
                active_duration=active_duration
            )
            db.session.add(attendance)
        
        # Reset student login status
        student.is_logged_in = False
        student.current_room = None
        student.login_time = None
        student.last_active_time = None
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Room {room_code} closed successfully'})

# ... rest of existing routes ...
# Student registration
@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        username = request.form.get('username')
        password = request.form.get('password')
        face_image = request.form.get('face_image')
        
        existing_student = Student.query.filter_by(username=username).first()
        if existing_student:
            flash("Username already exists")
            return redirect(url_for('register_student'))
            
        # Process and save face image
        face_encoding, message = process_face_image(face_image)
        if not face_encoding:
            flash(f"Face registration failed: {message}")
            return redirect(url_for('register_student'))
        
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_student = Student(
            student_id=student_id,
            username=username,
            password=hashed_password,
            face_encoding=face_encoding
        )
        
        db.session.add(new_student)
        db.session.commit()
        
        flash("Registration successful")
        return redirect(url_for('login_student'))
        
    return render_template('register_student.html')

# Student login
@app.route('/login_student', methods=['GET', 'POST'])
def login_student():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        face_image = request.form.get('face_image')
        room_code = request.form.get('room_code')  # Added room code field
        
        student = Student.query.filter_by(username=username).first()
        
        if not student:
            flash("Invalid username or password")
            return redirect(url_for('login_student'))
            
        if not bcrypt.check_password_hash(student.password, password):
            flash("Invalid username or password")
            return redirect(url_for('login_student'))
        
        # Verify face
        face_verified, message = verify_face(student.student_id, face_image)
        if not face_verified:
            flash(f"Face verification failed: {message}")
            return redirect(url_for('login_student'))
        
        # Verify room code exists and is active
        room = Room.query.filter_by(room_code=room_code, active=True).first()
        if not room:
            flash("Invalid or inactive room code")
            return redirect(url_for('login_student'))
        
        # Verify BSSID matches the room's BSSID
        current_bssid = get_wifi_bssid()
        if current_bssid != room.bssid:
            flash("You must be connected to the same network as the admin who created this room")
            return redirect(url_for('login_student'))
            
        # Set login info
        student.is_logged_in = True
        student.login_time = datetime.now()
        student.last_active_time = datetime.now()
        student.current_room = room_code
        
        db.session.commit()
        
        session['student_id'] = student.id
        session['student_username'] = student.username
        session['current_room'] = room_code
        
        return redirect(url_for('student_dashboard'))
        
    # Get list of active rooms for dropdown
    active_rooms = Room.query.filter_by(active=True).all()
    return render_template('login_student.html', active_rooms=active_rooms)

# Student dashboard
@app.route('/student_dashboard')
def student_dashboard():
    if 'student_id' not in session:
        flash("Please login first")
        return redirect(url_for('login_student'))
        
    student_id = session.get('student_id')
    student = Student.query.get(student_id)
    
    return render_template('student_dashboard.html', student=student)

# Logout route
@app.route('/logout', methods=['GET', 'POST'])
def logout():
    if 'student_id' in session:
        student_id = session.get('student_id')
        student = Student.query.get(student_id)
        
        if student and student.is_logged_in:
            # Create attendance record
            if student.login_time:
                active_duration = (datetime.now() - student.login_time).total_seconds() / 60
                attendance = AttendanceRecord(
                    student_id=student.student_id,
                    room_code=student.current_room,
                    login_time=student.login_time,
                    logout_time=datetime.now(),
                    active_duration=active_duration
                )
                db.session.add(attendance)
            
            # Reset student login status
            student.is_logged_in = False
            student.current_room = None
            student.login_time = None
            student.last_active_time = None
            db.session.commit()
            
        # Clear session
        session.pop('student_id', None)
        session.pop('student_username', None)
        session.pop('current_room', None)
        
    elif 'admin_id' in session:
        session.pop('admin_id', None)
        session.pop('admin_username', None)
        
    return redirect(url_for('index'))

# Admin start session
@app.route('/start_session', methods=['POST'])
def start_session():
    if 'admin_id' not in session:
        return jsonify({'message': 'Admin not logged in'}), 401
    
    admin_id = session['admin_id']
    admin = Admin.query.get(admin_id)
    admin.session_active = True
    db.session.commit()
    
    return jsonify({'message': 'Session started successfully'})

# Admin end session
@app.route('/end_session', methods=['POST'])
def end_session():
    if 'admin_id' not in session:
        return jsonify({'message': 'Admin not logged in'}), 401
    
    admin_id = session['admin_id']
    admin = Admin.query.get(admin_id)
    
    # End all active rooms for this admin
    active_rooms = Room.query.filter_by(admin_id=admin_id, active=True).all()
    for room in active_rooms:
        room.active = False
        
        # Log out all students in the room
        students_in_room = Student.query.filter_by(current_room=room.room_code, is_logged_in=True).all()
        for student in students_in_room:
            # Create attendance record
            if student.login_time:
                active_duration = (datetime.now() - student.login_time).total_seconds() / 60
                attendance = AttendanceRecord(
                    student_id=student.student_id,
                    room_code=room.room_code,
                    login_time=student.login_time,
                    logout_time=datetime.now(),
                    active_duration=active_duration
                )
                db.session.add(attendance)
            
            # Reset student login status
            student.is_logged_in = False
            student.current_room = None
            student.login_time = None
            student.last_active_time = None
    
    admin.session_active = False
    db.session.commit()
    
    return jsonify({'message': 'Session ended successfully'})

# Update student activity
@app.route('/update_activity', methods=['POST'])
def update_activity():
    if 'student_id' in session:
        student_id = session.get('student_id')
        student = Student.query.get(student_id)
        
        if student:
            student.last_active_time = datetime.now()
            db.session.commit()
            
    return jsonify({'success': True})

# Get active students for admin dashboard
@app.route('/active_students')
def active_students():
    if 'admin_id' not in session:
        return jsonify([])
    
    students_list = []
    active_students = Student.query.filter_by(is_logged_in=True).all()
    
    for student in active_students:
        # Calculate active time
        if student.login_time:
            active_duration = datetime.now() - student.login_time
            hours, remainder = divmod(active_duration.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            active_time = f"{hours:02}:{minutes:02}:{seconds:02}"
        else:
            active_time = "00:00:00"
        
        # Check if student is active within last 2 minutes
        status = "Active"
        if student.last_active_time and (datetime.now() - student.last_active_time).seconds > 120:
            status = "Inactive"
            
        students_list.append({
            'student_id': student.student_id,
            'username': student.username,
            'status': status,
            'active_time': active_time,
            'room': student.current_room
        })
    
    return jsonify(students_list)

# Download attendance records
@app.route('/download_attendance')
def download_attendance():
    if 'admin_id' not in session:
        flash("Please login first")
        return redirect(url_for('login_admin'))
    
    # Create a temporary CSV file
    import tempfile
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    
    with open(temp_file.name, 'w', newline='') as csvfile:
        fieldnames = ['student_id', 'room_code', 'login_time', 'logout_time', 'active_duration']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        records = AttendanceRecord.query.all()
        
        for record in records:
            writer.writerow({
                'student_id': record.student_id,
                'room_code': record.room_code,
                'login_time': record.login_time,
                'logout_time': record.logout_time,
                'active_duration': f"{record.active_duration:.2f} minutes"
            })
    
    return send_file(temp_file.name, as_attachment=True, download_name='attendance.csv')

if __name__ == '__main__':
    app.run(host="0.0.0.0",port=5000 ,ssl_context=("cert.pem", "key.pem"))