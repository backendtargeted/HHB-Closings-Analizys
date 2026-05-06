"""
Flask application main file
"""

from flask import Flask
from flask_cors import CORS

from .api.routes import api_bp, load_reports_from_disk
from .api.patches import patches_bp

app = Flask(__name__)

# Align with Docker/nginx `client_max_body_size` (512m) for multipart uploads
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024

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

# Register API blueprints
app.register_blueprint(api_bp, url_prefix="/api")
app.register_blueprint(patches_bp, url_prefix="/api/patches")


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
