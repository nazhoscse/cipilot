# Render Deployment Guide for CIPilot

## Database Setup with Render Disk (SSD)

CIPilot uses SQLite for analytics, which requires **persistent storage** on Render. The `render.yaml` is already configured with a disk mount.

### Disk Configuration

The `render.yaml` includes:

```yaml
disk:
  name: cipilot-data
  mountPath: /var/data
  sizeGB: 1  # 1GB SSD disk
envVars:
  - key: DATABASE_PATH
    value: /var/data/cipilot_analytics.db
```

### How It Works

1. **Render Disk**: A 1GB persistent SSD disk named `cipilot-data` is attached to the backend service
2. **Mount Path**: The disk is mounted at `/var/data` in the container
3. **Database Location**: SQLite database will be created at `/var/data/cipilot_analytics.db`
4. **Automatic Creation**: The database file and tables are created automatically on first startup
5. **Persistence**: Data survives container restarts and redeployments

### Deployment Steps

#### 1. Push to GitHub

```bash
git add .
git commit -m "Prepare for Render deployment"
git push origin main
```

#### 2. Create Render Account & Deploy

1. Go to [render.com](https://render.com) and sign up/login
2. Click **New** → **Blueprint**
3. Connect your GitHub repository
4. Select the repository containing `render.yaml`
5. Click **Apply**

Render will:
- Create the backend service with the persistent disk
- Create the frontend static site
- Set up environment variables
- Deploy both services

#### 3. Verify Disk Attachment

After deployment:
1. Go to your backend service dashboard
2. Click on **Disk** tab
3. Verify `cipilot-data` is attached and mounted at `/var/data`

#### 4. Update Frontend API URL

1. Go to the frontend service (`cipilot-web`)
2. Navigate to **Environment** tab
3. Update `VITE_API_URL` with your backend URL:
   - Format: `https://cipilot-api.onrender.com`
   - Replace `<cipilot-api-url>` placeholder
4. Save and trigger redeploy

### Database Management

#### Accessing the Database

Connect to your backend service shell:

```bash
# Via Render Dashboard → Shell
sqlite3 /var/data/cipilot_analytics.db
```

#### View Analytics Data

```sql
-- View detection logs
SELECT id, repo_full_name, detected_services, created_at 
FROM detection_logs 
ORDER BY created_at DESC 
LIMIT 10;

-- View migration logs
SELECT id, repo_full_name, target_platform, final_status, created_at 
FROM migration_logs 
ORDER BY created_at DESC 
LIMIT 10;

-- View sessions
SELECT id, user_id, last_activity_at 
FROM user_sessions 
ORDER BY last_activity_at DESC 
LIMIT 10;
```

#### Backup Database

Download the database file via Render Shell:

```bash
# In Render Shell
cat /var/data/cipilot_analytics.db > /tmp/backup.db
```

Then download from the Render dashboard.

### Disk Size Considerations

**Current**: 1GB SSD disk

**Estimated Capacity**:
- ~10,000 migrations with full YAML storage
- ~100,000 detection events
- Can be increased via Render dashboard if needed

### Monitoring

Check disk usage in Render Shell:

```bash
du -sh /var/data
ls -lh /var/data/cipilot_analytics.db
```

### Troubleshooting

#### Database Not Creating

Check logs:
```bash
# In service logs, look for:
[DATABASE] SQLite initialized at: /var/data/cipilot_analytics.db
```

#### Permission Issues

The Dockerfile sets `chmod 777 /var/data` to ensure write permissions.

If issues persist:
```bash
# In Render Shell
ls -la /var/data
# Should show rwxrwxrwx permissions
```

#### Disk Full

Increase disk size:
1. Go to backend service → Disk tab
2. Increase `sizeGB` value
3. Redeploy

### Cost Estimate

- **Disk**: $0.25/GB/month = **$0.25/month** for 1GB
- **Backend (Starter)**: $7/month
- **Frontend (Static)**: Free
- **Total**: ~$7.25/month

### Environment Variables

| Variable | Value | Description |
|----------|-------|-------------|
| `DATABASE_PATH` | `/var/data/cipilot_analytics.db` | Path to SQLite database on persistent disk |
| `VITE_API_URL` | `https://cipilot-api.onrender.com` | Backend API URL for frontend |

### Health Checks

The backend includes a health check that verifies:
- Service is responding
- Database connection is working

Check at: `https://cipilot-api.onrender.com/`

### Production Considerations

1. **WAL Mode**: Database uses WAL mode for better concurrency
2. **Session Timeout**: 30-minute inactivity timeout
3. **Background Tasks**: Analytics logged asynchronously
4. **Automatic Commits**: All database operations include commits

### Next Steps

After deployment:
1. Test detection on a repository
2. Verify logs appear in database
3. Monitor disk usage
4. Set up alerts if needed

### Support

- Render Docs: https://render.com/docs/disks
- SQLite Docs: https://www.sqlite.org/wal.html
