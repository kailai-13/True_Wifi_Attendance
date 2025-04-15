from flask import Flask, render_template, session, redirect, url_for, flash, request, jsonify, send_file
import subprocess
import re
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import csv
from datetime import datetime, timedelta
import os
import threading
import time
import io 
from ultralytics import YOLO
import cv2
import numpy as np
import base64
import json
import os
import uuid
from datetime import datetime # Added for in-memory file handling

# Create directory for storing face images if it doesn't exist
os.makedirs('face_data', exist_ok=True)
face_model = YOLO('yolov8n.pt')

app = Flask(__name__)

# Provide a default database URI (required for SQLAlchemy to work)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///default.db'

# Define multiple database bindings
app.config['SQLALCHEMY_BINDS'] = {
    'admin_db': 'sqlite:///admin.db',
    'student_db': 'sqlite:///students.db',
    'room_db': 'sqlite:///rooms.db'  # Database for room management
}

app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Silence the deprecation warning

from flask_session import Session
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

class Room(db.Model):
    __bind_key__ = 'room_db'
    id = db.Column(db.Integer, primary_key=True)
    room_code = db.Column(db.String(50), nullable=False, unique=True)
    admin_id = db.Column(db.Integer, nullable=False)  # ID of admin who created the room
    created_at = db.Column(db.DateTime, default=datetime.now)
    active = db.Column(db.Boolean, default=True)
    temporarily_closed = db.Column(db.Boolean, default=False)  # New field for temporary closing
    bssid = db.Column(db.String(100))  # Store the BSSID when room was created
# Add these new fields to the RoomMember model
class RoomMember(db.Model):
    __bind_key__ = 'room_db'
    id = db.Column(db.Integer, primary_key=True)
    room_code = db.Column(db.String(50), db.ForeignKey('room.room_code'), nullable=False)
    roll_number = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    is_registered = db.Column(db.Boolean, default=False)  # Track if student has registered
    status = db.Column(db.String(20), default='Not Present')  # Not Present, Present, OD, Excused
    
    # Composite unique constraint
    __table_args__ = (db.UniqueConstraint('room_code', 'roll_number', name='_room_roll_uc'),)
# Update the Student model with room info and roll number

class Student(db.Model):
    __bind_key__ = 'student_db'
    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(50), nullable=False, unique=True)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(100), nullable=False)
    current_room = db.Column(db.String(50))  # Store current room code
    current_bssid = db.Column(db.String(100))  # Store student's current BSSID
    face_image_path = db.Column(db.String(200))  # Path to stored face image
    
    is_logged_in = db.Column(db.Boolean, default=False)
    login_time = db.Column(db.DateTime)
    last_active_time = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
class AttendanceRecord(db.Model):
    __bind_key__ = 'student_db'
    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(50), db.ForeignKey('student.roll_number'))
    room_code = db.Column(db.String(50))
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
            if match:
                return match.group(1)
        elif system == "Linux":
            # Try multiple Linux commands
            try:
                result = subprocess.run(["iwconfig"], capture_output=True, text=True)
                match = re.search(r'Access Point: ([0-9A-Fa-f:]+)', result.stdout)
                if match:
                    return match.group(1)
            except FileNotFoundError:
                try:
                    result = subprocess.run(["iw", "dev"], capture_output=True, text=True)
                    match = re.search(r'addr ([0-9A-Fa-f:]+)', result.stdout)
                    if match:
                        return match.group(1)
                except FileNotFoundError:
                    pass
        elif system == "Darwin":  # macOS
            try:
                result = subprocess.run(["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"], capture_output=True, text=True)
                match = re.search(r'BSSID: ([0-9A-Fa-f:]+)', result.stdout)
                if match:
                    return match.group(1)
            except FileNotFoundError:
                pass
        
        # If we get here, we couldn't get the BSSID with platform-specific methods
        # Generate a unique identifier based on hostname and IP for this session
        import socket
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        return f"HOST-{hostname}-{ip}"  # Use a prefix to identify this is a hostname-based ID
            
    except Exception as e:
        # Log the error but don't fail - return a placeholder value instead
        print(f"Error getting BSSID: {e}")
        return "BSSID-UNAVAILABLE"

# Function to extract face from image data
def extract_face(image_data):
    try:
        # Decode base64 image
        encoded_data = image_data.split(',')[1]
        nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Detect faces using YOLOv8
        results = face_model(img)
        
        # Check if any face is detected
        if len(results[0].boxes) == 0:
            return None, "No face detected"
        
        # Get the bounding box of the first detected face
        boxes = results[0].boxes
        box = boxes[0].xyxy[0].cpu().numpy()  # Get the coordinates of the first face
        x1, y1, x2, y2 = map(int, box)
        
        # Extract the face
        face = img[y1:y2, x1:x2]
        
        # Resize for consistency
        face = cv2.resize(face, (112, 112))
        
        return face, None
    except Exception as e:
        return None, str(e)

hog = cv2.HOGDescriptor(
    _winSize=(64, 64),
    _blockSize=(16, 16),
    _blockStride=(8, 8),
    _cellSize=(8, 8),
    _nbins=9
)


def compare_faces(face1, face2, threshold=0.7):
    try:
        face1 = cv2.resize(face1, (64, 64))
        face2 = cv2.resize(face2, (64, 64))
        
        gray1 = cv2.cvtColor(face1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(face2, cv2.COLOR_BGR2GRAY)
        
        feat1 = hog.compute(gray1)
        feat2 = hog.compute(gray2)
        
        feat1 = feat1 / np.linalg.norm(feat1)
        feat2 = feat2 / np.linalg.norm(feat2)

        similarity = np.dot(feat1.flatten(), feat2.flatten())
        return similarity > threshold
    except Exception as e:
        print(f"Error comparing faces: {e}")
        return False

# Background thread to check WiFi connection of all logged-in students
def check_wifi_connections():
    with app.app_context():
        while True:
            try:
                # Get all logged-in students
                active_students = Student.query.filter_by(is_logged_in=True).all()
                
                for student in active_students:
                    if not student.current_room:
                        continue
                        
                    # Get the room's BSSID
                    room = Room.query.filter_by(room_code=student.current_room).first()
                    if not room:
                        continue
                    
                    # If the student's BSSID doesn't match the room's BSSID, mark as inactive
                    if student.current_bssid != room.bssid:
                        student.is_active = False
                        db.session.commit()
                
                # Sleep for a few seconds before checking again
                time.sleep(5)
            except Exception as e:
                print(f"Error in WiFi check thread: {e}")
                time.sleep(10)  # Wait longer if there's an error

# Start the WiFi check thread when the app starts
wifi_thread = threading.Thread(target=check_wifi_connections, daemon=True)
wifi_thread.start()

# Main index route
@app.route('/')
def index():
    bssid = get_wifi_bssid()
    return render_template('index.html', bssid=bssid)

@app.route('/register_face', methods=['POST'])
def register_face():
    if request.method == 'POST':
        data = request.json
        image_data = data.get('image_data')
        
        if not image_data:
            return jsonify({'success': False, 'message': 'No image data provided'})
        
        # Extract face from image
        face, error = extract_face(image_data)
        if error:
            return jsonify({'success': False, 'message': error})
        
        # Generate unique filename for the face
        face_id = str(uuid.uuid4())
        filename = f"{face_id}.jpg"
        filepath = os.path.join('face_data', filename)
        
        # Save face image
        cv2.imwrite(filepath, face)
        
        return jsonify({
            'success': True, 
            'message': 'Face registered successfully', 
            'face_id': face_id
        })
    
# Admin registration
@app.route('/register_admin', methods=['GET', 'POST'])
def register_admin():
    if request.method == 'POST':
        idname = request.form.get('idname')
        username = request.form.get('username')
        password = request.form.get('password')
        
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

# Modified Room model with 'temporarily_closed' field
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        flash("Please login first")
        return redirect(url_for('login_admin'))
    
    # Get all rooms created by this admin
    admin_id = session.get('admin_id')
    rooms = Room.query.filter_by(admin_id=admin_id).all()
    
    return render_template('admin_dashboard.html', rooms=rooms)

# Create a new room
@app.route('/create_room', methods=['POST'])
def create_room():
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
        
    room_code = request.form.get('room_code')
    
    # Check if room code already exists
    existing_room = Room.query.filter_by(room_code=room_code).first()
    if existing_room:
        # If room exists but belongs to this admin, just reactivate it
        admin_id = session.get('admin_id')
        if existing_room.admin_id == admin_id:
            # Get admin's current BSSID
            admin = Admin.query.get(admin_id)
            current_bssid = get_wifi_bssid()
            admin.current_bssid = current_bssid
            
            # Update room with current BSSID and set active
            existing_room.bssid = current_bssid
            existing_room.active = True
            existing_room.temporarily_closed = False
            db.session.commit()
            return jsonify({'success': True, 'message': f'Room {room_code} reopened successfully'})
        else:
            return jsonify({'success': False, 'message': 'Room code already exists'})
    
    # Get admin's current BSSID
    admin_id = session.get('admin_id')
    admin = Admin.query.get(admin_id)
    current_bssid = get_wifi_bssid()
    admin.current_bssid = current_bssid
    
    # Create new room
    new_room = Room(
        room_code=room_code,
        admin_id=admin_id,
        bssid=current_bssid,
        active=True,
        temporarily_closed=False
    )
    
    db.session.add(new_room)
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Room {room_code} created successfully'})

# Temporarily close a room
@app.route('/temporarily_close_room/<room_code>', methods=['POST'])
def temporarily_close_room(room_code):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})

    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()

    if not room:
        return jsonify({'success': False, 'message': 'Room not found'})

    # Log out all students in the room
    students_in_room = Student.query.filter_by(current_room=room_code, is_logged_in=True).all()
    for student in students_in_room:
        if student.login_time:
            active_duration = (datetime.now() - student.login_time).total_seconds() / 60
            attendance = AttendanceRecord(
                roll_number=student.roll_number,
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
        student.current_bssid = None
        student.is_active = True  # Reset active status

    # Mark all room members as not present
    room_members = RoomMember.query.filter_by(room_code=room_code).all()
    for member in room_members:
        member.status = 'Not Present'
    
    # Mark room as temporarily closed
    room.temporarily_closed = True
    room.active = False
    db.session.commit()

    return jsonify({'success': True, 'message': f'Room {room_code} temporarily closed'})

# Open a temporarily closed room
@app.route('/open_room/<room_code>', methods=['POST'])
def open_room(room_code):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})

    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()

    if not room:
        return jsonify({'success': False, 'message': 'Room not found'})
    
    # Get admin's current BSSID
    current_bssid = get_wifi_bssid()
    admin = Admin.query.get(admin_id)
    admin.current_bssid = current_bssid
    
    # Update room status and BSSID
    room.temporarily_closed = False
    room.active = True
    room.bssid = current_bssid
    db.session.commit()

    return jsonify({'success': True, 'message': f'Room {room_code} opened successfully'})


# Add room members
@app.route('/add_room_members/<room_code>', methods=['GET', 'POST'])
def add_room_members(room_code):
    if 'admin_id' not in session:
        flash("Please login first")
        return redirect(url_for('login_admin'))
    
    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()
    
    if not room:
        flash("Room not found or you don't have permission")
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        roll_number = request.form.get('roll_number')
        username = request.form.get('username')
        
        # Check if member already exists in this room
        existing_member = RoomMember.query.filter_by(
            room_code=room_code, 
            roll_number=roll_number
        ).first()
        
        if existing_member:
            flash(f"Member with roll number {roll_number} already exists in this room")
            return redirect(url_for('add_room_members', room_code=room_code))
        
        # Add new member
        new_member = RoomMember(
            room_code=room_code,
            roll_number=roll_number,
            username=username,
            is_registered=False
        )
        
        db.session.add(new_member)
        db.session.commit()
        
        flash(f"Member {username} ({roll_number}) added successfully")
    
    # Display current members
    members = RoomMember.query.filter_by(room_code=room_code).all()
    
    return render_template('add_room_members.html', 
                           room=room, 
                           members=members)
@app.route('/room_members/<room_code>')
def get_room_members(room_code):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
    
    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()
    
    if not room:
        return jsonify({'success': False, 'message': 'Room not found or you don\'t have permission'})
    
    # Get all members for this room
    members = RoomMember.query.filter_by(room_code=room_code).order_by(RoomMember.roll_number).all()
    
    # Build member list with status
    member_list = []
    for member in members:
        # Check if student is online
        student = Student.query.filter_by(
            roll_number=member.roll_number,
            current_room=room_code,
            is_logged_in=True
        ).first()
        
        active_status = "N/A"
        active_time = "N/A"
        
        if student:
            # Calculate active time
            if student.login_time:
                active_duration = datetime.now() - student.login_time
                hours, remainder = divmod(active_duration.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                active_time = f"{hours:02}:{minutes:02}:{seconds:02}"
            
            # Check connection status
            active_status = "Active" if student.is_active else "Inactive (WiFi Disconnected)"
            
            # Also check if student is active within last 2 minutes as a backup
            if student.is_active and student.last_active_time and (datetime.now() - student.last_active_time).seconds > 120:
                active_status = "Inactive (No Activity)"
        
        member_list.append({
            'roll_number': member.roll_number,
            'username': member.username,
            'status': member.status,
            'active_status': active_status if member.status == 'Present' else "N/A",
            'active_time': active_time if member.status == 'Present' else "N/A",
            'is_registered': member.is_registered
        })
    
    # Count statistics
    total_members = len(member_list)
    present_count = sum(1 for m in member_list if m['status'] == 'Present')
    od_count = sum(1 for m in member_list if m['status'] == 'OD')
    excused_count = sum(1 for m in member_list if m['status'] == 'Excused')
    
    return jsonify({
        'success': True,
        'members': member_list,
        'stats': {
            'total': total_members,
            'present': present_count,
            'od': od_count,
            'excused': excused_count
        }
    })
# Bulk upload members via CSV
@app.route('/upload_members/<room_code>', methods=['POST'])
def upload_members(room_code):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
    
    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()
    
    if not room:
        return jsonify({'success': False, 'message': 'Room not found or you don\'t have permission'})
    
    # Check if file was uploaded
    if 'csv_file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'})
    
    file = request.files['csv_file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'})
    
    # Process CSV file
    try:
        csv_content = file.read().decode('utf-8').splitlines()
        csv_reader = csv.reader(csv_content)
        next(csv_reader)  # Skip header row
        
        count = 0
        for row in csv_reader:
            if len(row) >= 2:  # Make sure we have roll_number and username
                roll_number = row[0].strip()
                username = row[1].strip()
                
                # Check if member already exists
                existing_member = RoomMember.query.filter_by(
                    room_code=room_code, 
                    roll_number=roll_number
                ).first()
                
                if not existing_member:
                    new_member = RoomMember(
                        room_code=room_code,
                        roll_number=roll_number,
                        username=username,
                        is_registered=False
                    )
                    db.session.add(new_member)
                    count += 1
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'{count} members added successfully'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error processing file: {str(e)}'})

# Delete room member
@app.route('/delete_room_member/<room_code>/<int:member_id>', methods=['POST'])
def delete_room_member(room_code, member_id):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
    
    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()
    
    if not room:
        return jsonify({'success': False, 'message': 'Room not found or you don\'t have permission'})
    
    member = RoomMember.query.get(member_id)
    if not member or member.room_code != room_code:
        return jsonify({'success': False, 'message': 'Member not found'})
    
    db.session.delete(member)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Member removed successfully'})
# New route to mark student as excused or on duty
@app.route('/update_student_status', methods=['POST'])
def update_student_status():
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
    
    roll_number = request.form.get('roll_number')
    room_code = request.form.get('room_code')
    status = request.form.get('status')  # 'OD' or 'Excused'
    
    if not all([roll_number, room_code, status]) or status not in ['OD', 'Excused', 'Not Present']:
        return jsonify({'success': False, 'message': 'Invalid parameters'})
    
    # Find the room member
    member = RoomMember.query.filter_by(room_code=room_code, roll_number=roll_number).first()
    if not member:
        return jsonify({'success': False, 'message': 'Student not found in this room'})
    
    # Update status
    member.status = status
    
    # If student is logged in and being marked as OD or Excused, update their status too
    student = Student.query.filter_by(roll_number=roll_number, current_room=room_code).first()
    if student and student.is_logged_in:
        # For excused students, we'll still keep them logged in but marked as excused
        # For OD students, we'll log them out
        if status == 'OD':
            # Create attendance record
            if student.login_time:
                active_duration = (datetime.now() - student.login_time).total_seconds() / 60
                attendance = AttendanceRecord(
                    roll_number=student.roll_number,
                    room_code=room_code,
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
    return jsonify({'success': True, 'message': f'Student marked as {status}'})

# Permanently close/delete a room
@app.route('/close_room/<room_code>', methods=['POST'])
def close_room(room_code):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})

    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()

    if not room:
        return jsonify({'success': False, 'message': 'Room not found'})

    # Log out all students in the room
    students_in_room = Student.query.filter_by(current_room=room_code, is_logged_in=True).all()
    for student in students_in_room:
        if student.login_time:
            active_duration = (datetime.now() - student.login_time).total_seconds() / 60
            attendance = AttendanceRecord(
                roll_number=student.roll_number,
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
        student.current_bssid = None
        student.is_active = True  # Reset active status

    # Delete room members
    RoomMember.query.filter_by(room_code=room_code).delete()
    
    # Delete the room
    db.session.delete(room)
    db.session.commit()

    return jsonify({'success': True, 'message': f'Room {room_code} permanently closed'})
@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        roll_number = request.form.get('roll_number')
        room_code = request.form.get('room_code')
        username = request.form.get('username')
        password = request.form.get('password')
        face_id = request.form.get('face_id')
        
        # Verify face ID exists
        if not face_id:
            flash("Face registration is required")
            return redirect(url_for('register_student'))
            
        face_path = os.path.join('face_data', f"{face_id}.jpg")
        if not os.path.exists(face_path):
            flash("Face data not found, please try again")
            return redirect(url_for('register_student'))
        
        # Verify that this student is allowed in this room
        room_member = RoomMember.query.filter_by(
            room_code=room_code,
            roll_number=roll_number
        ).first()
        
        if not room_member:
            flash("Invalid registration details. Please check your roll number and room code.")
            return redirect(url_for('register_student'))

        # Check if member is already registered
        if room_member.is_registered:
            flash("This student is already registered for this room")
            return redirect(url_for('register_student'))

        # Verify username matches what admin provided
        if room_member.username != username:
            flash("The username does not match what was assigned by the admin")
            return redirect(url_for('register_student'))
        
        # Check if roll number is already registered
        existing_student = Student.query.filter_by(roll_number=roll_number).first()
        if existing_student:
            flash("This roll number is already registered")
            return redirect(url_for('register_student'))
        
        # Create new student account with face image path
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_student = Student(
            roll_number=roll_number,
            username=username,
            password=hashed_password,
            face_image_path=face_path,
            is_active=True
        )
        
        # Mark as registered in room members
        room_member.is_registered = True
        
        try:
            db.session.add(new_student)
            db.session.commit()
            flash("Registration successful")
            return redirect(url_for('login_student'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error during registration: {str(e)}")
            return redirect(url_for('register_student'))
    
    # Get all active rooms for dropdown
    active_rooms = Room.query.filter_by(active=True).all()
    return render_template('register_student.html', active_rooms=active_rooms)

# Endpoint to verify face during student login
@app.route('/verify_face', methods=['POST'])
def verify_face():
    data = request.json
    image_data = data.get('image_data')
    roll_number = data.get('roll_number')
    
    if not image_data or not roll_number:
        return jsonify({'success': False, 'message': 'Missing data'})
    
    # Find student
    student = Student.query.filter_by(roll_number=roll_number).first()
    if not student or not student.face_image_path:
        return jsonify({'success': False, 'message': 'Student face data not found'})
    
    # Extract face from login attempt
    login_face, error = extract_face(image_data)
    if error:
        return jsonify({'success': False, 'message': error})
    
    # Load the registered face
    registered_face = cv2.imread(student.face_image_path)
    if registered_face is None:
        return jsonify({'success': False, 'message': 'Could not load registered face data'})
    
    # Compare faces
    match = compare_faces(login_face, registered_face)
    # print(match)
    
    if match:
        return jsonify({'success': True, 'message': 'Face verification successful'})
    else:
        return jsonify({'success': False, 'message': 'Face does not match. Please try again.'})

# FIXED: Check if eligible to register - Fixed to properly check existence
@app.route('/check_eligibility', methods=['POST'])
def check_eligibility():
    roll_number = request.form.get('roll_number')
    room_code = request.form.get('room_code')
    
    # Check if already registered as a student
    existing_student = Student.query.filter_by(roll_number=roll_number).first()
    if existing_student:
        return jsonify({
            'eligible': False,
            'message': 'This roll number is already registered'
        })
    
    # Find matching room member
    room_member = RoomMember.query.filter_by(
        room_code=room_code,
        roll_number=roll_number
    ).first()
    
    if not room_member:
        return jsonify({
            'eligible': False,
            'message': 'You are not on the list for this room'
        })
    
    # Check if member is already registered
    if room_member.is_registered:
        return jsonify({
            'eligible': False,
            'message': 'This student is already registered for this room'
        })
        
    return jsonify({
        'eligible': True,
        'username': room_member.username,
        'message': 'You are eligible to register'
    })

# Modified login_student route to check for temporarily_closed rooms
# Modified login student route to include face verification
@app.route('/login_student', methods=['GET', 'POST'])
def login_student():
    if request.method == 'POST':
        roll_number = request.form.get('roll_number')
        password = request.form.get('password')
        room_code = request.form.get('room_code')
        face_verified = request.form.get('face_verified')
        
        # Ensure face verification was completed
        if face_verified != 'true':
            flash("Face verification is required")
            return redirect(url_for('login_student'))
        
        student = Student.query.filter_by(roll_number=roll_number).first()
        
        if not student:
            flash("Invalid roll number or password")
            return redirect(url_for('login_student'))
            
        if not bcrypt.check_password_hash(student.password, password):
            flash("Invalid roll number or password")
            return redirect(url_for('login_student'))
        
        # Rest of the login code remains the same...
        # Check if student is a member of this room
        room_member = RoomMember.query.filter_by(
            room_code=room_code,
            roll_number=roll_number,
            is_registered=True
        ).first()
        
        if not room_member:
            flash("You are not registered for this room")
            return redirect(url_for('login_student'))
        
        # Verify room code exists and is active (not temporarily closed)
        room = Room.query.filter_by(room_code=room_code, active=True, temporarily_closed=False).first()
        if not room:
            flash("Room is inactive or temporarily closed")
            return redirect(url_for('login_student'))
        
        # Verify BSSID matches the room's BSSID with improved handling
        current_bssid = get_wifi_bssid()
        
        # Modified BSSID check logic
        if current_bssid.startswith("HOST-") and room.bssid.startswith("HOST-"):
            # Compare just the IP part or match if on same machine
            same_network = (current_bssid.split('-')[-1] == room.bssid.split('-')[-1]) or (
                current_bssid.split('-')[1] == room.bssid.split('-')[1])
            if not same_network:
                flash("You must be connected to the same network as the admin who created this room")
                return redirect(url_for('login_student'))
        elif (current_bssid.startswith("BSSID-UNAVAILABLE") or 
              room.bssid.startswith("BSSID-UNAVAILABLE")):
            # If we couldn't determine BSSID on either end, skip the check
            pass
        elif current_bssid != room.bssid:
            # Normal BSSID comparison for when we have actual BSSIDs
            flash("You must be connected to the same network as the admin who created this room")
            return redirect(url_for('login_student'))
            
        # Set login info
        student.is_logged_in = True
        student.login_time = datetime.now()
        student.last_active_time = datetime.now()
        student.current_room = room_code
        student.current_bssid = current_bssid
        student.is_active = True
        
        # Update room member status
        room_member.status = 'Present'
        
        db.session.commit()
        
        session['student_id'] = student.id
        session['student_username'] = student.username
        session['current_room'] = room_code
        
        return redirect(url_for('student_dashboard'))
        
    # Get list of active rooms for dropdown (only not temporarily closed)
    active_rooms = Room.query.filter_by(active=True, temporarily_closed=False).all()
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

# Endpoint for the client to report its current BSSID
@app.route('/update_wifi_status', methods=['POST'])
def update_wifi_status():
    if 'student_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
        
    student_id = session.get('student_id')
    student = Student.query.get(student_id)
    
    if not student or not student.current_room:
        return jsonify({'success': False, 'message': 'Student not properly logged in'})
    
    # Get current BSSID
    current_bssid = get_wifi_bssid()
    
    # Get the room's expected BSSID
    room = Room.query.filter_by(room_code=student.current_room).first()
    if not room:
        return jsonify({'success': False, 'message': 'Room not found'})
    
    # Update student's current BSSID
    student.current_bssid = current_bssid
    
    # Modified BSSID comparison logic
    if current_bssid.startswith("HOST-") and room.bssid.startswith("HOST-"):
        # Compare just the IP part or match if on same machine
        student.is_active = (current_bssid.split('-')[-1] == room.bssid.split('-')[-1]) or (
            current_bssid.split('-')[1] == room.bssid.split('-')[1])
    elif (current_bssid.startswith("BSSID-UNAVAILABLE") or 
          room.bssid.startswith("BSSID-UNAVAILABLE")):
        # If we couldn't determine BSSID on either end, assume they're active
        student.is_active = True
    else:
        # Normal BSSID comparison
        student.is_active = (current_bssid == room.bssid)
    
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'is_active': student.is_active,
        'current_bssid': current_bssid,
        'expected_bssid': room.bssid
    })

# Logout route
# Modified to update a student's status on logout
@app.route('/logout', methods=['POST'])
def logout():
    if 'student_id' in session:
        student_id = session.get('student_id')
        student = Student.query.get(student_id)

        if student and student.is_logged_in:
            # Create attendance record
            if student.login_time:
                active_duration = (datetime.now() - student.login_time).total_seconds() / 60
                attendance = AttendanceRecord(
                    roll_number=student.roll_number,
                    room_code=student.current_room,
                    login_time=student.login_time,
                    logout_time=datetime.now(),
                    active_duration=active_duration
                )
                db.session.add(attendance)

            # Update room member status when student logs out
            room_member = RoomMember.query.filter_by(
                room_code=student.current_room,
                roll_number=student.roll_number
            ).first()
            
            if room_member and room_member.status == 'Present':
                room_member.status = 'Not Present'

            # Reset student login status
            student.is_logged_in = False
            student.current_room = None
            student.login_time = None
            student.last_active_time = None
            student.current_bssid = None
            student.is_active = True  # Reset active status
            db.session.commit()

        # Clear student session
        session.pop('student_id', None)
        session.pop('student_username', None)
        session.pop('current_room', None)

    elif 'admin_id' in session:
        session.pop('admin_id', None)
        session.pop('admin_username', None)

    return jsonify({'success': True, 'message': 'Logged out successfully', 'redirect': url_for('index')})

# Update student activity
@app.route('/update_activity', methods=['POST'])
def update_activity():
    if 'student_id' in session:
        student_id = session.get('student_id')
        student = Student.query.get(student_id)
        
        if student:
            student.last_active_time = datetime.now()
            
            # Also check WiFi connection
            if student.current_room:
                room = Room.query.filter_by(room_code=student.current_room).first()
                if room:
                    current_bssid = get_wifi_bssid()
                    student.current_bssid = current_bssid
                    student.is_active = (current_bssid == room.bssid)
            
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
        
        # Check if student is connected to correct WiFi
        status = "Active" if student.is_active else "Inactive (No Activity)"
        
        # Also check if student is active within last 2 minutes as a backup
        if student.is_active and student.last_active_time and (datetime.now() - student.last_active_time).seconds > 30:
            status = "Inactive (No Activity)"
            
        students_list.append({
            'roll_number': student.roll_number,
            'username': student.username,
            
            'status': status,
            'active_time': active_time,
            'room': student.current_room
        })
    
    return jsonify(students_list)


@app.route('/download_attendance/<room_code>')
def download_attendance(room_code):
    if 'admin_id' not in session:
        flash("Please login first")
        return redirect(url_for('login_admin'))
    
    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()
    
    if not room:
        flash("Room not found or you don't have permission")
        return redirect(url_for('admin_dashboard'))
    
    # Get all members for this room, ordered by roll number
    members = RoomMember.query.filter_by(room_code=room_code).order_by(RoomMember.roll_number).all()
    
    # Create a temporary CSV file
    import tempfile
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    
    with open(temp_file.name, 'w', newline='') as csvfile:
        fieldnames = [
            'roll_number', 
            'username', 
            'status', 
            'is_registered', 
            'active_status', 
            'login_time', 
            'active_duration'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        
        for member in members:
            # Get student info if available
            student = Student.query.filter_by(
                roll_number=member.roll_number,
                current_room=room_code,
                is_logged_in=True
            ).first()
            
            login_time = "N/A"
            active_duration = "N/A"
            active_status = "N/A"
            
            if student and member.status == 'Present':
                # Calculate active duration
                if student.login_time:
                    login_time = student.login_time.strftime('%Y-%m-%d %H:%M:%S')
                    duration_minutes = (datetime.now() - student.login_time).total_seconds() / 60
                    active_duration = f"{duration_minutes:.2f} minutes"
                
                # Check connection status
                active_status = "Active" if student.is_active else "Inactive (WiFi Disconnected)"
                
                # Also check if student is active within last 2 minutes as a backup
                if student.is_active and student.last_active_time and (datetime.now() - student.last_active_time).seconds > 120:
                    active_status = "Inactive (No Activity)"
            
            writer.writerow({
                'roll_number': member.roll_number,
                'username': member.username,
                'status':  "Was Present But Then Disconnected" if active_status=="Inactive (No Activity)" else member.status ,
                'is_registered': "Yes" if member.is_registered else "No",
                'active_status': active_status if member.status == 'Present' else "N/A",
                'login_time': login_time,
                'active_duration': active_duration
            })
    
    return send_file(
        temp_file.name,
        as_attachment=True,
        download_name=f'attendance_{room_code}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )


@app.route('/download_student_attendance')
def download_student_attendance():
    if 'student_id' not in session:
        flash("Please login first")
        return redirect(url_for('login_student'))
    
    student_id = session.get('student_id')
    student = Student.query.get(student_id)
    
    if not student:
        flash("Student not found")
        return redirect(url_for('login_student'))

    # Get all attendance records for this student
    records = AttendanceRecord.query.filter_by(roll_number=student.roll_number).order_by(AttendanceRecord.login_time.desc()).all()

    # Create temporary CSV file
    import tempfile
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    
    with open(temp_file.name, 'w', newline='') as csvfile:
        fieldnames = [
            'roll_number',
            'username',
            'room_code', 
            'login_time', 
            'logout_time', 
            'active_duration(minutes)',
            'status'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        
        for record in records:
            # Determine status based on logout time
            status = "Completed" if record.logout_time else "Active" if student.is_logged_in and student.current_room == record.room_code else "Incomplete"
            
            writer.writerow({
                'roll_number': student.roll_number,
                'username': student.username,
                'room_code': record.room_code,
                'login_time': record.login_time.strftime('%Y-%m-%d %H:%M:%S'),
                'logout_time': record.logout_time.strftime('%Y-%m-%d %H:%M:%S') if record.logout_time else "N/A",
                'active_duration(minutes)': f"{record.active_duration:.2f}" if record.active_duration else "N/A",
                'status': status
            })
    
    return send_file(
        temp_file.name,
        as_attachment=True,
        download_name=f'attendance_history_{student.roll_number}.csv'
    )


# Endpoint to get all rooms (active, temporarily closed, permanent) for the current admin
@app.route('/get_admin_rooms')
def get_admin_rooms():
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
    
    admin_id = session.get('admin_id')
    rooms = Room.query.filter_by(admin_id=admin_id).all()
    
    room_list = []
    for room in rooms:
        status = "Active"
        if room.temporarily_closed:
            status = "Temporarily Closed"
        elif not room.active:
            status = "Inactive"
            
        room_list.append({
            'room_code': room.room_code,
            'created_at': room.created_at.strftime('%Y-%m-%d %H:%M'),
            'status': status,
            'bssid': room.bssid
        })
    
    return jsonify({'success': True, 'rooms': room_list})

if __name__ == '__main__':
    app.run(host="0.0.0.0",port=5000 ,ssl_context=("cert.pem", "key.pem"),debug=True)