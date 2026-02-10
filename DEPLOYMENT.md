# Deployment Guide

## Current Situation

You have existing containers running (`hhboffers-*`) on ports:
- **80, 443** (Nginx)
- **3001** (App)
- **5432** (PostgreSQL - internal)
- **6379** (Redis - internal)

Your new **Contact Attribution Analysis** app uses:
- **8000** (Backend API)
- **3000** (Frontend)

✅ **No port conflicts** - safe to deploy alongside existing containers.

## Deployment Steps

### 1. Verify Current Containers
```bash
docker ps
```

### 2. Build and Start New Containers
From the project root directory:
```bash
docker-compose up -d --build
```

This will:
- Build both frontend and backend images
- Create containers: `contact-attribution-backend` and `contact-attribution-frontend`
- Start them in detached mode (`-d`)
- Use a separate network: `contact-attribution-network`

### 3. Verify Deployment
```bash
# Check all running containers
docker ps

# Check logs
docker-compose logs -f

# Check specific service logs
docker-compose logs backend
docker-compose logs frontend
```

### 4. Test Access
- **Frontend**: http://your-server-ip:3000
- **Backend API**: http://your-server-ip:8000
- **Health Check**: http://your-server-ip:8000/health

## Container Management

### View Running Containers
```bash
docker ps
```

### Stop Containers
```bash
docker-compose stop
```

### Start Containers
```bash
docker-compose start
```

### Restart Containers
```bash
docker-compose restart
```

### Stop and Remove Containers
```bash
docker-compose down
```

### Stop and Remove Containers + Volumes
```bash
docker-compose down -v
```

### Update Deployment (After Code Changes)
```bash
docker-compose up -d --build
```

## Network Isolation

The new containers use a dedicated network (`contact-attribution-network`) which:
- Keeps them isolated from your `hhboffers` containers
- Allows frontend and backend to communicate internally
- Prevents any conflicts with existing services

## Port Mapping

- **Frontend**: Host port `3000` → Container port `80` (Nginx)
- **Backend**: Host port `8000` → Container port `8000` (Flask/Gunicorn)

## Troubleshooting

### Port Already in Use
If you get a port conflict error:
```bash
# Check what's using the port
netstat -tulpn | grep :8000
netstat -tulpn | grep :3000

# Or on Linux
ss -tulpn | grep :8000
```

### Container Won't Start
```bash
# Check logs
docker-compose logs backend
docker-compose logs frontend

# Check container status
docker ps -a
```

### Rebuild After Code Changes
```bash
docker-compose up -d --build --force-recreate
```

### View Container Resource Usage
```bash
docker stats
```

## Production Considerations

1. **Reverse Proxy**: Consider adding Nginx reverse proxy to route:
   - `/api/*` → Backend (port 8000)
   - `/*` → Frontend (port 3000)

2. **SSL/TLS**: Add SSL certificates for HTTPS access

3. **Environment Variables**: Use `.env` file for sensitive configuration:
   ```bash
   # Create .env file
   ENV=production
   # Add other variables as needed
   ```

4. **Data Persistence**: Volumes are already configured for:
   - `uploads/` - Uploaded files
   - `exports/` - Exported results
   - `reports/` - Saved reports

5. **Monitoring**: Consider adding health checks and monitoring

## Rollback

If you need to rollback:
```bash
# Stop containers
docker-compose down

# Remove images (optional)
docker rmi contact-attribution-backend contact-attribution-frontend
```

## Next Steps

After successful deployment:
1. Test file upload functionality
2. Verify analysis runs correctly
3. Check export functionality
4. Monitor logs for any errors
5. Set up regular backups of volumes if needed
