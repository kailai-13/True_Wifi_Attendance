import cv2
import torch
import numpy as np
from ultralytics import YOLO
from facenet_pytorch import InceptionResnetV1
from sklearn.metrics.pairwise import cosine_similarity
import pickle
import os

# Load YOLOv8 model
face_detector = YOLO("yolov8n-face.pt")  # Make sure you download this model

# Load FaceNet (Face Recognition Model)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
face_recognizer = InceptionResnetV1(pretrained='vggface2').eval().to(device)

# Check if embeddings file exists
if not os.path.exists('embeddings.pkl'):
    with open('embeddings.pkl', 'wb') as f:
        pickle.dump({}, f)

# Face Detection Function
def detect_faces(frame):
    results = face_detector(frame)
    boxes = results[0].boxes.xyxy.cpu().numpy() if results else []
    return boxes

# Face Registration Function
def register_user(user_id):
    cap = cv2.VideoCapture(0)
    print("Press SPACE to capture your face...")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        
        boxes = detect_faces(frame)
        for (x1, y1, x2, y2) in boxes:
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
        
        cv2.imshow('Register', frame)
        key = cv2.waitKey(1)
        
        if key == 32 and len(boxes) > 0:  # SPACE key
            x1, y1, x2, y2 = boxes[0]
            face = frame[int(y1):int(y2), int(x1):int(x2)]
            face_rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
            face_tensor = torch.from_numpy(face_rgb).permute(2, 0, 1).float().to(device) / 255.0
            
            with torch.no_grad():
                embedding = face_recognizer(face_tensor.unsqueeze(0)).cpu().numpy()
            
            with open('embeddings.pkl', 'rb') as f:
                embeddings = pickle.load(f)
            embeddings[user_id] = embedding
            with open('embeddings.pkl', 'wb') as f:
                pickle.dump(embeddings, f)
            print(f"User {user_id} registered successfully!")
            break
    
    cap.release()
    cv2.destroyAllWindows()

# Face Login Function
def login_user():
    cap = cv2.VideoCapture(0)
    print("Press SPACE to attempt login...")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        
        boxes = detect_faces(frame)
        for (x1, y1, x2, y2) in boxes:
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
        
        cv2.imshow('Login', frame)
        key = cv2.waitKey(1)
        
        if key == 32 and len(boxes) > 0:  # SPACE key
            x1, y1, x2, y2 = boxes[0]
            face = frame[int(y1):int(y2), int(x1):int(x2)]
            face_rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
            face_tensor = torch.from_numpy(face_rgb).permute(2, 0, 1).float().to(device) / 255.0
            
            with torch.no_grad():
                embedding = face_recognizer(face_tensor.unsqueeze(0)).cpu().numpy()
            
            with open('embeddings.pkl', 'rb') as f:
                embeddings = pickle.load(f)
            
            max_similarity = -1
            matched_user = None
            for user_id, saved_embed in embeddings.items():
                similarity = cosine_similarity(embedding, saved_embed)[0][0]
                if similarity > max_similarity:
                    max_similarity = similarity
                    matched_user = user_id
            
            if max_similarity > 0.7:
                print(f"Welcome, {matched_user}! Similarity: {max_similarity:.2f}")
            else:
                print("Login failed. No matching user found.")
            break
    
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    while True:
        print("\n1. Register\n2. Login\n3. Exit")
        choice = input("Choose an option: ")
        
        if choice == '1':
            user_id = input("Enter user ID: ")
            register_user(user_id)
        elif choice == '2':
            login_user()
        elif choice == '3':
            break
        else:
            print("Invalid choice. Try again.")