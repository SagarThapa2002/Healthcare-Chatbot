# 🏥 Healthcare Chatbot for Primary Care and Appointment Scheduling

A Dialogflow-integrated chatbot system that provides basic symptom checks and allows patients to book appointments using natural language.

---

## 📘 Final Year Project – CN6000  
**University of East London**

**Created by:** Sagar Thapa  
**Module:** CN6000 - Final Year Project  
**Supervisor:** *[Add your supervisor's name]*  
**Academic Year:** 2024/2025

---

## 🧠 Project Description

This project demonstrates a healthcare chatbot that:

- Accepts symptom-related queries and provides basic advice
- Enables patients to book an appointment with a doctor
- Uses Dialogflow ES for natural language understanding
- Has a Flask-based backend for webhook logic
- Stores booked appointments in a local JSON file
- Exposes an API endpoint to view all booked appointments

---

## 💡 Features

- **Symptom Checker**  
  Users can say things like:  
  `I have a headache` or `I'm feeling dizzy`.

- **Appointment Booking**  
  Users can book appointments with utterances like:  
  `I want to book an appointment for John on May 5th at 10am`.

- **Appointment Storage**  
  All appointments are stored in `appointments.json`.

- **API to View Appointments**  
  Access booked appointments via GET request to `/webhook/appointments`.

---

## ⚙️ Technologies Used

- **Dialogflow ES**
- **Python 3**
- **Flask**
- **Ngrok** – for tunneling localhost to Dialogflow
- **Git/GitHub** – for version control

---

## 🛠️ Installation & Setup

### Prerequisites

- Python 3.x
- Pip
- Ngrok
- Git

### Clone the Repository

```bash
git clone https://github.com/your-username/healthcare-chatbot.git
cd healthcare-chatbot/backend
pip install -r requirements.txt
python app.py
ngrok http 5000
