# CIPilot Documentation Structure

This document explains the organization of CIPilot's documentation.

## Public Documentation

These files are committed to the public GitHub repository:

### [README.md](README.md)
**Audience:** Public users, researchers, developers  
**Content:**
- Project overview and features
- Quick start guide
- API reference for public endpoints:
  - `POST /convert-cicd`
  - `POST /retry-conversion`
  - `POST /validate-github-actions`
- Deployment instructions (Render, Docker, self-hosted)
- Supported CI/CD platforms
- Troubleshooting guide

**What's NOT included:**
- ❌ Analytics endpoints
- ❌ Database schema details
- ❌ Internal monitoring tools
- ❌ Session tracking implementation

---

## Internal Documentation

These files exist **only on developer machines** and are excluded from version control via [.gitignore](.gitignore):

### INTERNAL_ANALYTICS.md
**Audience:** Internal developers, system administrators  
**Content:**
- Complete analytics system architecture
- Database schema (all 5 tables with detailed columns)
- Analytics API reference:
  - `GET /analytics/health` — Service health check
  - `GET /analytics/detections` — Detection logs with pagination
  - `GET /analytics/migrations` — Migration logs with pagination
  - `GET /analytics/sessions` — User sessions with pagination
  - `GET /analytics/stats` — Aggregated statistics
  - `POST /analytics/session` — Create new session
- Usage examples (curl commands, SQL queries)
- Session management (30-min timeout logic)
- Deployment configuration (DATABASE_PATH, disk setup)
- Maintenance & monitoring procedures
- Privacy & GDPR compliance notes
- Security considerations (authentication, encryption)

**Why it's internal:**
- Contains implementation details that could be exploited
- Reveals analytics collection methods
- Includes database credentials and paths
- Not relevant for public users

### RENDER_DATABASE_PERSISTENCE_TROUBLESHOOTING.md
**Audience:** DevOps, deployment engineers  
**Content:**
- Step-by-step troubleshooting for database persistence issues
- Render.com disk mount diagnostics
- Environment variable configuration
- Common deployment mistakes and solutions
- Shell commands for debugging
- Health check interpretation

**Why it's internal:**
- Contains sensitive deployment details
- Reveals infrastructure configuration
- Includes internal tooling commands
- Not applicable to general users

---

## Quick Reference

| Document | Public? | Purpose |
|----------|---------|---------|
| `README.md` | ✅ Yes | User guide, API docs, setup instructions |
| `IMPLEMENTATION_SUMMARY.md` | ✅ Yes | Technical implementation overview |
| `INTERNAL_ANALYTICS.md` | ❌ **No** | Analytics API docs, DB schema, monitoring |
| `RENDER_DATABASE_PERSISTENCE_TROUBLESHOOTING.md` | ❌ **No** | Deployment diagnostics, troubleshooting |

---

## For New Developers

### Accessing Internal Documentation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-org>/cipilot.git
   cd cipilot
   ```

2. **Internal docs already exist locally** (created during development)
   - If missing, contact the team lead to obtain copies
   - Place them in the project root directory
   - They are automatically ignored by `.gitignore`

3. **DO NOT commit internal docs:**
   ```bash
   # These commands should return empty (files are ignored):
   git status INTERNAL_ANALYTICS.md
   git status RENDER_DATABASE_PERSISTENCE_TROUBLESHOOTING.md
   ```

### Creating New Internal Documentation

If you need to add more internal docs:

1. Create the file in the project root
2. Add it to `.gitignore`:
   ```gitignore
   # Internal documentation (CONFIDENTIAL - do not commit)
   INTERNAL_ANALYTICS.md
   RENDER_DATABASE_PERSISTENCE_TROUBLESHOOTING.md
   YOUR_NEW_INTERNAL_DOC.md
   ```
3. Verify it's ignored: `git status` should not show it

---

## Updating Documentation

### Public Documentation (README.md)

- **Always safe to update** and commit to version control
- Changes will be visible to all users
- Review carefully for sensitive information before committing

### Internal Documentation

- **Update freely on your local machine**
- Changes stay local (not pushed to GitHub)
- Share updates with team via secure channels (Slack, email attachments, etc.)
- Do NOT commit, even accidentally

---

## Security Notes

🔒 **Internal documentation contains:**
- Database connection strings and paths
- Analytics collection methods
- Internal API endpoints
- Deployment credentials and configurations
- Debugging procedures

⚠️ **If internal docs are accidentally committed:**
1. Remove from git history: `git rm --cached INTERNAL_ANALYTICS.md`
2. Commit the removal: `git commit -m "Remove internal docs"`
3. Force push: `git push --force`
4. Rotate any exposed credentials
5. Review other commits for similar leaks

---

## Contact

For questions about documentation structure:
- **Public docs:** Open a GitHub issue
- **Internal docs:** Contact the development team directly
