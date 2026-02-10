# Development Setup Guide

## Quick Start (Without Docker)

### Option 1: Using Batch Script (Windows - Easiest)
Double-click `start-dev.bat` or run:
```bash
start-dev.bat
```

This will:
- Check for Python and Node.js
- Create virtual environment if needed
- Install dependencies if missing
- Start both servers in separate windows

### Option 2: Using PowerShell Script (Windows)
```powershell
.\start-dev.ps1
```

### Option 3: Using Node.js Script (Cross-platform)
```bash
npm run dev
```

### Option 4: Manual Start

#### Backend
```bash
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend (in a new terminal)
```bash
cd frontend
npm install  # First time only
npm run dev
```

## Prerequisites

1. **Python 3.11+**
   - Check: `python --version`
   - Install from: https://www.python.org/downloads/

2. **Node.js 18+**
   - Check: `node --version`
   - Install from: https://nodejs.org/

3. **Backend Dependencies**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

4. **Frontend Dependencies**
   ```bash
   cd frontend
   npm install
   ```

## Access Points

Once both servers are running:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **API Alternative Docs**: http://localhost:8000/redoc

## Troubleshooting

### Port Already in Use
If port 8000 or 3000 is already in use:
- **Backend**: Change port in `backend/app/main.py` or use `--port 8001`
- **Frontend**: Change port in `frontend/vite.config.ts`

### Python Not Found
- Make sure Python is in your PATH
- Try `python3` instead of `python` on some systems
- On Windows, you may need to add Python to PATH during installation

### Node Modules Not Found
```bash
cd frontend
npm install
```

### Backend Dependencies Missing
```bash
cd backend
pip install -r requirements.txt
```

### Virtual Environment (Recommended)
For backend, it's recommended to use a virtual environment:
```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
pip install -r requirements.txt
```

## Development Tips

- Backend auto-reloads on file changes (thanks to `--reload` flag)
- Frontend hot-reloads automatically (Vite feature)
- Check browser console and terminal for errors
- Backend logs appear in the terminal running uvicorn
- Frontend logs appear in the terminal running npm
