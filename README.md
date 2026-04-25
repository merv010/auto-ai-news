# auto-ai-news

Daily AI news reports from a small set of trusted sources.

Reports are published as GitHub Releases so each day has a stable, dated entry with clickable links, star ratings, reading-time estimates, and skipped-source notes.

Latest report: https://github.com/kantarcise/auto-ai-news/releases/latest

## Run locally

```bash
python3 -m unittest discover -s tests
python3 scripts/generate_report.py --output daily-ai-news.md
```

## Automation

The GitHub Actions workflow runs every day at `06:15 UTC` and can also be started manually from the Actions tab. It creates or updates a release named `Daily AI News - YYYY-MM-DD` with the tag `daily-YYYY-MM-DD`.
