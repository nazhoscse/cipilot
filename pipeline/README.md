# CIPilot Batch Pipeline

Mass-produce CI/CD migrations for thousands of repositories with a single command.

## Features

- **Batch Processing**: Process thousands of repos from CSV/JSON input
- **Multi-PAT Support**: Rotate GitHub tokens when rate limited
- **Configurable Strictness**: Control when PRs are created
- **Resume Capability**: Continue from where you left off
- **Real-time Progress**: Live dashboard showing progress
- **Detailed Reporting**: CSV output with per-repo status

## Installation

```bash
cd pipeline
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
python run.py --input repos.csv --output results.csv
```

### With Configuration

```bash
python run.py \
  --input repos.csv \
  --output results.csv \
  --strictness permissive \
  --pr-on-lint-fail \
  --pr-on-double-check-fail \
  --provider xai \
  --model grok-4-1-fast-reasoning \
  --api-key $XAI_API_KEY \
  --github-pats "$PAT1,$PAT2,$PAT3" \
  --concurrent 5 \
  --retries 3
```

### Dry Run (No PRs)

```bash
python run.py --input repos.csv --output results.csv --dry-run
```

### Resume Previous Run

```bash
python run.py --input repos.csv --output results.csv --resume
```

## Input Format

### CSV

```csv
repo_url,target_branch
https://github.com/owner/repo1,main
owner/repo2,master
nazhoscse/machine,main
```

### JSON

```json
[
  {"repo_url": "owner/repo1", "target_branch": "main"},
  {"repo_url": "owner/repo2", "target_branch": "master"}
]
```

## Strictness Levels

| Level | Lint Must Pass | Double-Check Must Pass | PR Created When |
|-------|---------------|------------------------|-----------------|
| `strict` | ✅ | ✅ | Both pass |
| `lint_only` | ✅ | ❌ | Lint passes |
| `permissive` | ❌ | ❌ | Always (for feedback) |
| `dry_run` | N/A | N/A | Never |

## Output Columns

| Column | Description |
|--------|-------------|
| `repo_url` | Input repository |
| `detected_ci` | CircleCI, Travis, GitLab, etc. |
| `detection_status` | success/failed/no_ci_found |
| `migration_status` | success/failed/skipped |
| `lint_valid` | true/false |
| `lint_errors` | Error messages |
| `double_check_status` | passed/failed/skipped |
| `double_check_confidence` | 0.0-1.0 |
| `pr_status` | created/skipped/failed |
| `pr_url` | GitHub PR URL |
| `overall_status` | success/partial/failed |
| `duration_seconds` | Time taken |

## Environment Variables

```bash
export GITHUB_PATS="pat1,pat2,pat3"  # Comma-separated PATs
export LLM_PROVIDER="xai"
export LLM_API_KEY="your-api-key"
export LLM_MODEL="grok-4-1-fast-reasoning"
```
