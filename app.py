from flask import Flask, render_template
from flask_cors import CORS
from backend.webhook import webhook_bp

# Create the Flask app
app = Flask(__name__, template_folder='templates')  # Ensure templates directory is specified
CORS(app)  # Allow requests from all origins (useful for frontend integration)

# Register the webhook Blueprint at the '/webhook' endpoint
app.register_blueprint(webhook_bp, url_prefix='/webhook')

# Route to serve the frontend
@app.route('/')
def index():
    return render_template('index.html')

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
