"""
File upload and handling utilities
"""

import os
import uuid
from pathlib import Path
import shutil

# Use absolute path based on backend directory
BACKEND_DIR = Path(__file__).parent.parent.parent
UPLOAD_DIR = BACKEND_DIR / "uploads"
EXPORT_DIR = BACKEND_DIR / "exports"
UPLOAD_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)


def save_uploaded_file(file_storage, file_type: str = "data") -> str:
    """
    Save an uploaded file and return its path.

    Args:
        file_storage: Werkzeug FileStorage from request.files
        file_type: Type identifier (e.g., "excel", "csv")

    Returns:
        Path to saved file
    """
    file_id = str(uuid.uuid4())
    extension = Path(file_storage.filename).suffix if file_storage.filename else ""
    filename = f"{file_type}_{file_id}{extension}"
    file_path = UPLOAD_DIR / filename

    file_storage.save(str(file_path))
    return str(file_path)


def delete_file(file_path: str) -> bool:
    """Delete a file if it exists."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
    except Exception:
        return False


def validate_excel_file(file_path: str) -> bool:
    """Validate that file is a valid Excel file."""
    try:
        import pandas as pd
        pd.read_excel(file_path, nrows=1)
        return True
    except Exception:
        return False


def validate_csv_file(file_path: str) -> bool:
    """Validate that file is a valid CSV file."""
    try:
        import pandas as pd
        pd.read_csv(file_path, nrows=1)
        return True
    except Exception:
        return False
