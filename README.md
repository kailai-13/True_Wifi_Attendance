Here's a comprehensive `README.md` file for your project:

```markdown
# Attendance Management System with Face Recognition

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Flask](https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white)
![OpenCV](https://img.shields.io/badge/opencv-%23white.svg?style=for-the-badge&logo=opencv&logoColor=white)
![SQLite](https://img.shields.io/badge/sqlite-%2307405e.svg?style=for-the-badge&logo=sqlite&logoColor=white)

A Flask-based web application for attendance tracking using face recognition and WiFi-based location verification.

## Features

- **Role-based access control** (Admin & Student)
- **Face recognition authentication** using YOLOv8
- **Real-time attendance tracking**
- **WiFi-based location verification** (BSSID matching)
- **Room management system** (create/close rooms)
- **CSV export** for attendance records
- **Responsive web interface**

## System Architecture

```
├── app.py                # Main application file
├── face_data/            # Stores registered face images
├── templates/            # HTML templates
│   ├── admin_dashboard.html
│   ├── login_admin.html
│   ├── register_student.html
│   └── ...
├── admin.db              # Admin database
├── students.db           # Student database
└── rooms.db              # Room management database
```

## Installation

### Prerequisites
- Python 3.7+
- pip package manager

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/attendance-system.git
   cd attendance-system
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Download YOLOv8 weights:
   ```bash
   wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt
   ```

4. Initialize databases:
   ```bash
   python init_db.py
   ```

## Usage

### Running the Application
```bash
python app.py
```

The system will be available at:
- Admin interface: `https://localhost:5000/login_admin`
- Student interface: `https://localhost:5000/login_student`

### Admin Credentials
First admin must register at `/register_admin`

### Key Endpoints
| Endpoint | Description |
|----------|-------------|
| `/create_room` | Create new attendance room |
| `/add_room_members` | Add students to room |
| `/verify_face` | Face verification API |
| `/download_attendance` | Export attendance records |

## Configuration

Edit `config.py` for:
```python
class Config:
    SECRET_KEY = 'your-secret-key-here'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///default.db'
    SESSION_TYPE = 'filesystem'
```

## API Documentation

### Face Verification API
```http
POST /verify_face
Content-Type: application/json

{
    "image_data": "base64_encoded_image",
    "roll_number": "STU001"
}
```

Response:
```json
{
    "success": true,
    "message": "Face verification successful"
}
```

## Screenshots

![Admin Dashboard](screenshots/admin_dashboard.png)
*Admin Dashboard Interface*

![Face Registration](screenshots/face_registration.png)
*Student Face Registration*

## Troubleshooting

**Issue**: Face recognition not working
- Solution: Ensure proper lighting during face capture

**Issue**: WiFi verification fails
- Solution: Check if on same network as admin

## License

MIT License

## Contributing

1. Fork the project
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Acknowledgments

- Ultralytics for YOLOv8 model
- Flask community for web framework
- OpenCV for computer vision capabilities
```

### Additional Recommendations:

1. Create a `requirements.txt` file with:
```
flask
flask-sqlalchemy
flask-bcrypt
flask-session
opencv-python
ultralytics
numpy
python-dotenv
```

2. Create an `init_db.py` for database initialization:
```python
from app import app, db

with app.app_context():
    db.create_all()
    print("Databases initialized successfully!")
```

3. Add a `.gitignore` file:
```
__pycache__/
*.pyc
*.db
face_data/*
.env
```

This README provides comprehensive documentation including:
- Badges for key technologies
- Clear installation instructions
- Usage examples
- API documentation
- Troubleshooting guide
- Contribution guidelines

Would you like me to add any specific sections or modify any part of this README?
