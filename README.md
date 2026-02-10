# Contact Attribution Analysis Tool

A modern web application for analyzing contact history for closed deals, built with React + Vite frontend and Flask backend.

## Features

- **Interactive File Upload**: Drag-and-drop interface for Excel and CSV files
- **Real-time Progress**: Polling-based progress updates during analysis
- **Interactive Charts**: Visualizations using Recharts
  - Contact count distribution
  - Channel breakdown (CC, SMS, DM)
- **Advanced Filtering**: Filter results by lead source, contact count, match status, and search
- **Export Options**: Export results as Excel, CSV, or JSON
- **Responsive Design**: Mobile-friendly interface with Tailwind CSS
- **Brand Identity**: Custom styling with navy blue (#1B3A57) and gold (#F4B942)

## Tech Stack

### Frontend
- React 18 + TypeScript
- Vite
- Tailwind CSS
- Recharts for visualizations
- React Query for data fetching
- React Dropzone for file uploads

### Backend
- Flask
- Python 3.11
- Pandas for data analysis
- Polling for progress updates

## Getting Started

### Prerequisites
- Node.js 18+
- Python 3.11+
- Docker and Docker Compose (optional)

### Local Development

#### Backend
```bash
cd backend
pip install -r requirements.txt
python -m flask --app app.main run --host 0.0.0.0 --port 8000 --debug
```

#### Frontend
```bash
cd frontend
npm install
npm run dev
```

The application will be available at:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000

### Docker Deployment

```bash
docker-compose up --build
```

This will start both backend and frontend services:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000

## Usage

1. Upload your closed deals Excel file and contact history CSV file
2. Click "Run Analysis" to start the analysis
3. View real-time progress updates
4. Explore results with interactive charts and filters
5. Export results in your preferred format

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── api/          # API routes and models
│   │   ├── services/     # Business logic
│   │   ├── utils/        # Utility functions
│   │   └── main.py       # Flask application
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── hooks/        # Custom hooks
│   │   ├── services/     # API client
│   │   └── types/        # TypeScript types
│   ├── package.json
│   └── Dockerfile
└── docker-compose.yml
```

## License

Proprietary - HHB
