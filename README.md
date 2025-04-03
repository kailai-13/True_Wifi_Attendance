Attendance Management System
A Flask-based application for tracking student attendance using WiFi BSSID verification

📌 Table of Contents
Introduction

Features

System Architecture

Database Schema

Workflow & Flowcharts

Installation & Setup

Usage Guide

API Endpoints

Screenshots

Future Enhancements

Contributing

License

📜 Introduction
This project is a WiFi-based attendance system that ensures students are physically present in a classroom by verifying their connection to the same WiFi network (BSSID) as the admin.

🔹 Key Concepts:

BSSID Matching: Ensures students are in the same network as the admin.

Real-time Tracking: Monitors active students and logs attendance.

Secure Authentication: Uses Flask-Login and Bcrypt for password hashing.

Multi-Room Support: Admins can create different rooms (classes).

✨ Features
✅ Admin Features:

Create/manage classrooms (rooms)

Add students to rooms via CSV or manual entry

Track real-time attendance with WiFi verification

Download attendance reports

✅ Student Features:

Register for classes (rooms)

Login with WiFi verification

View/download attendance history

✅ System Features:

Background WiFi monitoring

Automatic logout when disconnected

Session management

📐 System Architecture
High-Level Diagram
mermaid
Copy
graph TD
    A[Admin] -->|Creates| B[Room]
    B -->|Contains| C[Students]
    C -->|Connects to| D[WiFi BSSID]
    D -->|Verified by| E[Attendance System]
    E -->|Logs| F[Attendance Records]
Tech Stack
Backend: Flask (Python)

Database: SQLAlchemy (SQLite)

Authentication: Flask-Login + Bcrypt

WiFi Check: Subprocess (OS commands)

Frontend: HTML, CSS, Bootstrap

🗃 Database Schema
ER Diagram
mermaid
Copy
erDiagram
    ADMIN ||--o{ ROOM : "creates"
    ROOM ||--o{ ROOM_MEMBER : "has"
    STUDENT ||--o{ ATTENDANCE_RECORD : "logs"
    ROOM_MEMBER }|--|| STUDENT : "registers"
Tables
Table	Description
Admin	Admin credentials & session data
Room	Classroom info (BSSID, admin)
RoomMember	Students assigned to rooms
Student	Student login & WiFi status
AttendanceRecord	Timestamped login/logout records
🔄 Workflow & Flowcharts
1️⃣ Admin Workflow
mermaid
Copy
sequenceDiagram
    Admin->>Server: Login
    Server->>Admin: Dashboard
    Admin->>Server: Create Room
    Server->>DB: Store Room + BSSID
    Admin->>Server: Add Students (CSV/Manual)
    Server->>DB: Update RoomMember
2️⃣ Student Workflow
mermaid
Copy
sequenceDiagram
    Student->>Server: Register (Roll No + Room)
    Server->>DB: Verify in RoomMember
    Student->>Server: Login (WiFi Check)
    Server->>DB: Log Attendance
    Student->>Server: Download Records
⚙ Installation & Setup
Prerequisites
Python 3.8+

Pip

SQLite

Steps
Clone the repo:

bash
Copy
git clone https://github.com/your-repo/attendance-system.git
cd attendance-system
Install dependencies:

bash
Copy
pip install -r requirements.txt
Initialize the database:

bash
Copy
python init_db.py
Run the app:

bash
Copy
python app.py
(Uses SSL for security)

📊 Screenshots
Admin Dashboard	Student Login	Attendance Report
Admin Dashboard	Student Login	Report
🚀 Future Enhancements
Face Recognition (OpenCV integration)

Mobile App (Flutter for students)

Automated WiFi Scanning (No manual BSSID checks)

Analytics Dashboard (Charts.js for reports)

🤝 Contributing
Fork the repo

Create a new branch (git checkout -b feature)

Commit changes (git commit -m "Added feature")

Push (git push origin feature)

Open a PR

📜 License
MIT License - Free for academic/commercial use.