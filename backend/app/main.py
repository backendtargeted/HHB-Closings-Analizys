"""
Flask application main file
"""

from flask import Flask
from flask_cors import CORS

from .api.routes import api_bp, load_reports_from_disk

app = Flask(__name__)

# Load persisted reports from volume into memory
load_reports_from_disk()
app.config["JSON_SORT_KEYS"] = False

# CORS configuration
CORS(
    app,
    origins=["http://localhost:3000", "http://localhost:5173"],
    supports_credentials=True,
    allow_headers=["*"],
    methods=["GET", "POST", "OPTIONS"],
)

# Register API blueprint
app.register_blueprint(api_bp, url_prefix="/api")


@app.route("/")
def root():
    """Root endpoint."""
    return {"message": "Contact Attribution Analysis API", "version": "1.0.0"}


@app.route("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
