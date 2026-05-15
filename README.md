# Contact Attribution Analysis Tool

A modern web application for analyzing contact history for closed deals, built with React + Vite frontend and Flask backend.

**Operations:** [RUNBOOK.md](RUNBOOK.md) — marketing → REISift → analysis pipeline, playbooks, API.

**Report methodology:** [docs/REPORT_METHODOLOGY.md](docs/REPORT_METHODOLOGY.md) — how tags are parsed, deduped, matched, counted, and turned into lifecycle metrics.

## Features

- **Contact-history analysis**: Derives closed deals from REISift **`Tags`** (optional legacy closings workbook)
- **Past patches**: Generate four REISift import CSVs (property/phone/SF tags/closings markers) from cold, SMS, CRM, closings inputs
- **Lead lifecycle**: Funnel stages, paths, first-touch, SF status trail from parsed tags
- **Resumable uploads**: Chunked large CSV upload via API (see RUNBOOK)
- **Interactive UI**: Charts (CC/SMS/DM), filters, Excel/CSV/JSON export (includes Lifecycle Events sheet)
- **Tag dedupe**: Identical tag tokens on one row are counted once (see methodology doc)

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
- Frontend: http://localhost:3300 (nginx; API proxied at `/api`)
- Backend API: http://localhost:8000 (direct; UI uses same-origin `/api` in Docker)

## Usage

1. **Regular analysis:** Export contacts from REISift (must include **`Tags`** and address columns). Upload the CSV in **Regular updates**. Closed deals are derived from tags such as `(CLOSED) 8020 - MM/YYYY` unless you use the legacy closings workbook path.
2. **Historical backfill (optional):** Use **Past patches** to build a REISift import zip, import into REISift, re-export, then analyze.
3. Run analysis, review lifecycle and contact counts, export Excel/CSV/JSON.

See [docs/REPORT_METHODOLOGY.md](docs/REPORT_METHODOLOGY.md) for counting rules and matching behavior.

## Project Structure

```
.
├── docs/
│   └── REPORT_METHODOLOGY.md   # How closings reports are computed
├── RUNBOOK.md                  # Operator workflows
├── backend/
│   ├── app/
│   │   ├── api/          # API routes and models
│   │   ├── services/     # analysis, lifecycle, marketing_mapper, cadence_from_history
│   │   ├── utils/        # Utility functions
│   │   └── main.py       # Flask application
│   ├── requirements.txt
│   └── Dockerfile
├── scripts/              # One-time ingest + cadence probe CLIs
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
