from flask import Flask
from webhook import webhook_bp

# Create the Flask app
app = Flask(__name__)

# Register the webhook Blueprint at the '/webhook' endpoint
app.register_blueprint(webhook_bp, url_prefix='/webhook')

# Default route to verify app is running
@app.route('/')
def index():
    return "Healthcare Chatbot Flask server is running!"

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
