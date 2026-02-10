# Git Setup Instructions

## Current Issue
There's a Git lock file preventing operations. This is usually caused by Cursor's Git integration or another Git process.

## Steps to Complete Git Setup

### 1. Close Git Operations in Cursor
- Close any Git-related panels or dialogs in Cursor
- Wait a few seconds for processes to release the lock

### 2. Stage All Files
Once the lock is cleared, run:
```powershell
cd "c:\Users\USER\Desktop\HHB 2024 Closings Analizys"
git add .
```

### 3. Create Initial Commit
```powershell
git commit -m "Initial commit: Contact Attribution Analysis Tool

- React + TypeScript frontend with Vite
- Flask backend with Pandas analysis
- Docker Compose setup
- File upload and analysis functionality
- Interactive charts and filtering
- Export capabilities (Excel, CSV, JSON)"
```

### 4. Set Up Remote Repository

#### Option A: If you have a GitHub/GitLab/Bitbucket repository URL:
```powershell
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

#### Option B: Create a new GitHub repository:
1. Go to https://github.com/new
2. Create a new repository (don't initialize with README)
3. Copy the repository URL
4. Run:
```powershell
git remote add origin <your-github-repo-url>
git branch -M main
git push -u origin main
```

### 5. If Lock File Persists

If the lock file still exists after closing Cursor Git operations:

**Windows PowerShell:**
```powershell
# Stop any Git processes
Get-Process | Where-Object {$_.ProcessName -like "*git*"} | Stop-Process -Force

# Remove lock file
Remove-Item ".git\index.lock" -Force

# Try again
git add .
```

**Or manually:**
1. Close Cursor completely
2. Open File Explorer
3. Navigate to `.git` folder
4. Delete `index.lock` file
5. Reopen Cursor and try again

## What's Included in the Commit

The `.gitignore` has been updated to exclude:
- ✅ `node_modules/` (Node.js dependencies)
- ✅ `dist/` and `build/` (build outputs)
- ✅ `__pycache__/` and `*.pyc` (Python cache)
- ✅ `backend/uploads/`, `backend/exports/`, `backend/reports/` (runtime data)
- ✅ `.env` files (environment variables)
- ✅ IDE files (`.vscode/`, `.idea/`)
- ✅ Data files (`2025 Closed Attribution.xlsx`, `cadence_measurement.csv`)

## Files Being Committed

- Source code (frontend/src, backend/app)
- Configuration files (package.json, requirements.txt, docker-compose.yml)
- Dockerfiles
- Documentation (README.md, README-DEV.md, DEPLOYMENT.md)
- Assets (HHB-Logo-600x143.webp)
