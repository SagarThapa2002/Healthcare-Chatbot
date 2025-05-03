from flask import Flask
from flask_cors import CORS
from backend.webhook import webhook_bp

# Create the Flask app
app = Flask(__name__)
CORS(app)  # Allow requests from all origins (useful for frontend integration)

# Register the webhook Blueprint at the '/webhook' endpoint
app.register_blueprint(webhook_bp, url_prefix='/webhook')

# Optional: root route just returns a simple message
@app.route('/')
def index():
    return {"message": "Healthcare Chatbot API is running."}

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
