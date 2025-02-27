function startSession() {
    fetch("/start_session", { method: "POST" })
    .then(response => response.json())
    .then(data => alert(data.message))
    .then(() => location.reload());
}

function endSession() {
    fetch("/end_session", { method: "POST" })
    .then(response => response.json())
    .then(data => alert(data.message))
    .then(() => location.reload());
}
// Update the updateStudentList function in admin-dashboard.html
function updateStudentList() {
    fetch("/active_students")
    .then(response => response.json())
    .then(data => {
        let tableBody = document.getElementById("student-list");
        tableBody.innerHTML = "";
        data.forEach(student => {
            let row = `<tr>
                <td>${student.student_id}</td>
                <td>${student.username}</td>
                <td>${student.status}</td>
                <td>${student.active_time}</td>
            </tr>`;
            tableBody.innerHTML += row;
        });
    });
}
setInterval(updateStudentList, 1000);  // Refresh every 2 seconds
function sendHeartbeat() {
    fetch('/update_activity', { method: 'POST' })
        .then(response => response.json())
        .then(data => { /* Optional handling */ });
}
// Send immediately and every 1 minute
sendHeartbeat();
setInterval(sendHeartbeat, 60000);

document.addEventListener('DOMContentLoaded', () => {
    const themeToggle = document.querySelector('.theme-toggle');
    const body = document.body;

    // Check for saved theme in localStorage
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
      body.setAttribute('data-theme', savedTheme);
    }

    // Toggle theme on button click
    themeToggle.addEventListener('click', () => {
      const currentTheme = body.getAttribute('data-theme');
      const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      body.setAttribute('data-theme', newTheme);
      localStorage.setItem('theme', newTheme); // Save theme to localStorage
    });
  });

// Access webcam
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const captureBtn = document.getElementById('capture-btn');
const loginBtn = document.getElementById('login-btn');
const captureStatus = document.getElementById('capture-status');
const faceImage = document.getElementById('face-image');

// Get access to the webcam
navigator.mediaDevices.getUserMedia({ video: true })
    .then(stream => {
        video.srcObject = stream;
    })
    .catch(err => {
        console.error('Error accessing camera:', err);
        captureStatus.textContent = 'Error: Cannot access camera';
        captureStatus.style.color = 'red';
    });
    
// Capture image from webcam
captureBtn.addEventListener('click', () => {
    const context = canvas.getContext('2d');
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const imageData = canvas.toDataURL('image/jpeg');
    
    // Store image data in hidden form field
    faceImage.value = imageData;
    
    captureStatus.textContent = 'Face captured! You can now login.';
    captureStatus.style.color = 'green';
    loginBtn.disabled = false;
});
function logoutOnDisconnect() {
    fetch("/logout", { method: "POST" });
}
window.addEventListener("beforeunload", logoutOnDisconnect);
