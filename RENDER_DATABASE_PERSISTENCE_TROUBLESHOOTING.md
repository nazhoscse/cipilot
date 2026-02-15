# Render Database Persistence Troubleshooting

## Problem
Database tables are being lost on each deployment despite setting `DATABASE_PATH` environment variable and attaching a persistent disk.

## Root Causes & Solutions

### 1. Disk Not Actually Mounted

**Symptoms:**
- `/var/data` directory doesn't exist
- Database falls back to `/app/data` (ephemeral)
- Files in `/var/data` disappear after redeploy

**Solution:**
1. Go to Render Dashboard → Your Service → Disks tab
2. Verify disk is **actually attached** (not just created)
3. Check mount path is exactly `/var/data`
4. Disk status should be "Active" not "Creating"

**How to verify:**
```bash
# SSH into Render shell
curl https://cipilot-api.onrender.com/analytics/health | python3 -m json.tool

# Should show:
{
  "disk_diagnostics": {
    "directory_exists": true,
    "directory_writable": true,
    "file_exists": true,
    "file_size_bytes": > 0
  }
}
```

### 2. Database File Created Before Disk Mount

**Symptoms:**
- Database file exists but is in `/app/data` instead of `/var/data`
- Tables exist but disappear on redeploy

**Why this happens:**
On Render, if your app starts **before** the disk is fully mounted, it creates the database in the fallback location (`/app/data`). Later when the disk mounts, your app continues using the old path.

**Solution:**
```bash
# In Render Dashboard → Shell:
# 1. Check current database location
ls -lh /var/data/
ls -lh /app/data/

# 2. If database is in /app/data, move it:
mv /app/data/cipilot_analytics.db* /var/data/

# 3. Restart the service
# Render Dashboard → Manual Deploy → Deploy Latest Commit
```

### 3. Incorrect Environment Variable

**Symptoms:**
- `database_env_var` shows "Not set" or wrong path
- App uses default `/app/data` location

**Solution:**
1. Render Dashboard → Your Service → Environment tab
2. Add environment variable:
   - Key: `DATABASE_PATH`
   - Value: `/var/data/cipilot_analytics.db`
3. Save and redeploy

**Verify:**
```bash
curl https://cipilot-api.onrender.com/analytics/health | python3 -m json.tool

# Should show:
{
  "database_env_var": "/var/data/cipilot_analytics.db",
  "actual_database_path": "/var/data/cipilot_analytics.db"
}
```

### 4. Disk Permissions Issue

**Symptoms:**
- Directory exists but app can't write to it
- `directory_writable: false` in health check

**Solution:**
```bash
# In Render Shell:
chmod 777 /var/data
chown -R render:render /var/data

# Or add to Dockerfile (already done):
RUN mkdir -p /var/data && chmod 777 /var/data
```

### 5. Blueprint Not Applied

**Symptoms:**
- Disk exists in Render but not attached to service
- Environment variable not set despite being in `render.yaml`

**Why this happens:**
Render Blueprints are only applied during **initial creation** or when you click "Apply Blueprint". Changes to `render.yaml` don't auto-update existing services.

**Solution:**
1. Go to Render Dashboard → Blueprints
2. Find your `cipilot` blueprint
3. Click "Apply Blueprint" or "Sync Blueprint"
4. Wait for deployment to complete

**OR manually configure:**
1. Disks tab → Attach existing disk `cipilot-data` to `/var/data`
2. Environment tab → Add `DATABASE_PATH=/var/data/cipilot_analytics.db`
3. Redeploy

## Diagnostic Commands

### Check Health Endpoint
```bash
curl https://cipilot-api.onrender.com/analytics/health | python3 -m json.tool
```

**What to look for:**
```json
{
  "status": "healthy",
  "database_env_var": "/var/data/cipilot_analytics.db",  // ✅ Should NOT be "Not set"
  "actual_database_path": "/var/data/cipilot_analytics.db",  // ✅ Should match env var
  "disk_diagnostics": {
    "directory_exists": true,  // ✅ Must be true
    "directory_writable": true,  // ✅ Must be true
    "file_exists": true,  // ✅ After first use
    "file_size_bytes": 32768,  // ✅ Should be > 0 after tables created
    "files_in_directory": ["cipilot_analytics.db", "cipilot_analytics.db-shm", "cipilot_analytics.db-wal"]  // ✅ WAL mode files
  }
}
```

### Check Database Tables
```bash
# In Render Shell:
sqlite3 /var/data/cipilot_analytics.db

# In SQLite prompt:
.tables
# Should show: analytics_events  detection_logs  migration_logs  user_sessions  users

# Check table count
SELECT COUNT(*) FROM sqlite_master WHERE type='table';
# Should return 5

# Exit
.quit
```

### Check Startup Logs
```bash
# Render Dashboard → Logs

# Look for these messages:
[DATABASE] Initializing at: /var/data/cipilot_analytics.db
[DATABASE] Directory exists: True
[DATABASE] Database file exists: True/False
[DATABASE] Database file size: X bytes
[DATABASE] Directory permissions: 777
[DATABASE] Initialization complete: 5 tables created
[DATABASE] Final file size: XXXXX bytes
```

### Check Disk Mount
```bash
# In Render Shell:
df -h | grep /var/data

# Should show something like:
# /dev/vdb  1.0G  32M  968M   4% /var/data
```

## Step-by-Step Fix Process

### Step 1: Verify Environment Variable
```bash
curl https://cipilot-api.onrender.com/analytics/health | python3 -m json.tool
```
- If `database_env_var` is "Not set", add it in Render Dashboard → Environment
- Redeploy after adding

### Step 2: Verify Disk Attachment
1. Render Dashboard → Your Service → Disks
2. Should show: `cipilot-data` attached to `/var/data`
3. Status should be "Active"

### Step 3: Check Health Again
```bash
curl https://cipilot-api.onrender.com/analytics/health | python3 -m json.tool
```
- `directory_exists` should be `true`
- `directory_writable` should be `true`

### Step 4: Verify Tables Exist
```bash
# SSH into Render shell
sqlite3 /var/data/cipilot_analytics.db
.tables
.quit
```

If tables don't exist:
```bash
# They will be created on first use. Trigger creation:
curl -X POST https://cipilot-api.onrender.com/analytics/session \
  -H "X-Analytics-User-ID: test_user_123"

# Then check again:
sqlite3 /var/data/cipilot_analytics.db
.tables
```

### Step 5: Test Persistence
1. Use the web app to create a detection and migration
2. Check data exists:
```bash
sqlite3 /var/data/cipilot_analytics.db
SELECT COUNT(*) FROM detection_logs;
SELECT COUNT(*) FROM migration_logs;
.quit
```

3. Trigger a redeploy (Render Dashboard → Manual Deploy)
4. After redeploy, check data still exists:
```bash
sqlite3 /var/data/cipilot_analytics.db
SELECT COUNT(*) FROM detection_logs;
# Should show same count as before
```

## Common Mistakes

### ❌ Using Dockerfile Volume
```dockerfile
VOLUME ["/var/data"]  # DON'T DO THIS ON RENDER
```
Dockerfile VOLUME doesn't create persistent storage on Render. You must use Render's Disk feature.

### ❌ Wrong Mount Path
```yaml
disk:
  mountPath: /data  # ❌ Wrong - doesn't match DATABASE_PATH
```
```yaml
disk:
  mountPath: /var/data  # ✅ Correct - matches DATABASE_PATH
```

### ❌ Blueprint Not Synced
Making changes to `render.yaml` doesn't auto-update existing services. You must:
1. Commit and push changes
2. Render Dashboard → Blueprints → Apply Blueprint

### ❌ Database Already Created in Wrong Location
If database was created in `/app/data` before disk mounted, app keeps using it. Solution:
```bash
# Move to correct location
mv /app/data/cipilot_analytics.db* /var/data/
# Restart service
```

## Expected Behavior After Fix

1. **On First Deployment:**
   - App creates `/var/data/cipilot_analytics.db`
   - Tables are created (5 tables total)
   - Database file size ~32KB

2. **On Subsequent Deployments:**
   - Existing database file is reused
   - No tables are recreated (IF NOT EXISTS)
   - Data persists across deployments

3. **After First Detection:**
   - `detection_logs` table has data
   - Database file size increases

4. **After First Migration:**
   - `migration_logs` table has data
   - `user_sessions` table has session data

## Quick Diagnosis Checklist

- [ ] `DATABASE_PATH` environment variable is set in Render
- [ ] Disk `cipilot-data` exists and is attached
- [ ] Mount path is `/var/data`
- [ ] Health endpoint shows `directory_exists: true`
- [ ] Health endpoint shows `directory_writable: true`
- [ ] Health endpoint shows correct paths (both should be `/var/data/cipilot_analytics.db`)
- [ ] Startup logs show "Initializing at: /var/data/cipilot_analytics.db"
- [ ] SQLite `.tables` command shows 5 tables
- [ ] Data persists after redeploy

If ALL checkboxes are checked and data still disappears, check Render support for disk issues.
