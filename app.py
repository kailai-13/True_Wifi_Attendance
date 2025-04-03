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
import io  # Added for in-memory file handling

# Create directory for storing face images if it doesn't exist
os.makedirs('face_data', exist_ok=True)

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

# Room Table (Stored in room_db)
class Room(db.Model):
    __bind_key__ = 'room_db'
    id = db.Column(db.Integer, primary_key=True)
    room_code = db.Column(db.String(50), nullable=False, unique=True)
    admin_id = db.Column(db.Integer, nullable=False)  # ID of admin who created the room
    created_at = db.Column(db.DateTime, default=datetime.now)
    active = db.Column(db.Boolean, default=True)
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
    
    is_logged_in = db.Column(db.Boolean, default=False)
    login_time = db.Column(db.DateTime)
    last_active_time = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)  # Track if student is connected to correct WiFi

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
        else:  # Linux / macOS
            result = subprocess.run(["iwconfig"], capture_output=True, text=True)
            match = re.search(r'Access Point: ([0-9A-Fa-f:]+)', result.stdout)

        return match.group(1) if match else "BSSID not found"
    except Exception as e:
        return str(e)

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

# Admin dashboard
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
# Modified to get all room members for admin dashboard
@app.route('/room_members/<room_code>')
def get_room_members(room_code):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'message': 'Admin not logged in'})
    
    admin_id = session.get('admin_id')
    room = Room.query.filter_by(room_code=room_code, admin_id=admin_id).first()
    
    if not room:
        return jsonify({'success': False, 'message': 'Room not found or you don\'t have permission'})
    
    # Get all members for this room
    members = RoomMember.query.filter_by(room_code=room_code).all()
    
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

    return jsonify({'success': True, 'message': f'Room {room_code} closed successfully'})

# FIXED: Student registration - Fixed to properly check existence
@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        roll_number = request.form.get('roll_number')
        room_code = request.form.get('room_code')
        username = request.form.get('username')
        password = request.form.get('password')
        
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
        
        # Create new student account
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_student = Student(
            roll_number=roll_number,
            username=username,
            password=hashed_password,
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

# Update to room login to update member status
@app.route('/login_student', methods=['GET', 'POST'])
def login_student():
    if request.method == 'POST':
        roll_number = request.form.get('roll_number')
        password = request.form.get('password')
        room_code = request.form.get('room_code')
        
        student = Student.query.filter_by(roll_number=roll_number).first()
        
        if not student:
            flash("Invalid roll number or password")
            return redirect(url_for('login_student'))
            
        if not bcrypt.check_password_hash(student.password, password):
            flash("Invalid roll number or password")
            return redirect(url_for('login_student'))
        
        # Check if student is a member of this room
        room_member = RoomMember.query.filter_by(
            room_code=room_code,
            roll_number=roll_number,
            is_registered=True
        ).first()
        
        if not room_member:
            flash("You are not registered for this room")
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
        student.current_bssid = current_bssid
        student.is_active = True
        
        # Update room member status
        room_member.status = 'Present'
        
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
    
    # Update student's current BSSID and active status
    student.current_bssid = current_bssid
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
        status = "Active" if student.is_active else "Inactive (WiFi Disconnected)"
        
        # Also check if student is active within last 2 minutes as a backup
        if student.is_active and student.last_active_time and (datetime.now() - student.last_active_time).seconds > 120:
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
    
    # Create a temporary CSV file
    import tempfile
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    
    with open(temp_file.name, 'w', newline='') as csvfile:
        fieldnames = ['roll_number', 'username', 'login_time', 'current_status', 'active_duration']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        
        # Get only currently active students in this room
        active_students = Student.query.filter_by(
            current_room=room_code, 
            is_logged_in=True
        ).all()
        
        for student in active_students:
            # Calculate active duration for currently logged in students
            active_duration = 0
            if student.login_time:
                active_duration = (datetime.now() - student.login_time).total_seconds() / 60
            
            writer.writerow({
                'roll_number': student.roll_number,
                'username': student.username,
                'login_time': student.login_time.strftime('%Y-%m-%d %H:%M:%S'),
                'current_status': "Active" if student.is_active else "Inactive",
                'active_duration': f"{active_duration:.2f} minutes"
            })
    
    return send_file(
        temp_file.name,
        as_attachment=True,
        download_name=f'current_attendance_{room_code}.csv'
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
    
if __name__ == '__main__':
    app.run(host="0.0.0.0",port=5000 ,ssl_context=("cert.pem", "key.pem"),debug=True)