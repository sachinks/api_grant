# Scripts — Per-Source Usage Guide

Each script is a standalone CLI entry point for one grant data source.
All scripts share the same flags and output format.

---

## Common Flags

| Flag | Description | Default |
|------|-------------|---------|
| `--date YYYY-MM-DD` | Pull records for this date | Yesterday |
| `--debug` | Enable verbose DEBUG logging to console | Off |

---

## 01 — NIH RePORTER

**Source:** National Institutes of Health (USA)
**API:** `https://api.reporter.nih.gov/v2/projects/search`
**Method:** POST (JSON body)
**Cadence:** Daily

```bash
python scripts/nih_reporter.py
python scripts/nih_reporter.py --date 2025-01-15
python scripts/nih_reporter.py --date 2025-01-15 --debug
```

**Output:** `NIH_YYYYMMDD.xlsx`

**Limitations:** None. Server-side date filter, full pagination support, PI and institution in response.

---

## 02 — NSF Awards

**Source:** National Science Foundation (USA)
**API:** `https://api.nsf.gov/services/v1/awards`
**Method:** GET (query params)
**Cadence:** Daily

```bash
python scripts/nsf_awards.py
python scripts/nsf_awards.py --date 2025-01-15
python scripts/nsf_awards.py --date 2025-01-15 --debug
```

**Output:** `NSF_YYYYMMDD.xlsx`

**Limitations:**
- Max 25 records per page (API enforced) — more pagination calls than NIH.
- Max 3,000 total results per query — dates with very high award volume may be truncated.

---

## 03 — CORDIS (EU Grants)

**Source:** Community Research and Development Information Service (EU)
**API:** `https://cordis.europa.eu/api`
**Method:** GET (query params)
**Cadence:** Weekly (up to 1,000 records)

```bash
python scripts/cordis_eu.py
python scripts/cordis_eu.py --date 2025-01-15
python scripts/cordis_eu.py --date 2025-01-15 --debug
```

**Output:** `CORDIS_YYYYMMDD.xlsx`

**Limitations:**
- Server is **geo-restricted** in some environments (WSL2, cloud IPs). Requests time out completely. Run from a network that can reach EU servers or use an EU VPN.
- PI names (`FIRST`, `LAST`) are **not available** in the CORDIS search API — these columns will be blank for all records.
- Intended as a **weekly** pull. Running daily returns the same records repeatedly within the same 7-day window.

---

## 04 — UKRI Gateway

**Source:** UK Research and Innovation
**API:** `https://gtr.ukri.org/api`
**Method:** GET (query params)
**Cadence:** Daily

```bash
python scripts/ukri_gateway.py
python scripts/ukri_gateway.py --date 2025-01-15
python scripts/ukri_gateway.py --date 2025-01-15 --debug
```

**Output:** `UKRI_YYYYMMDD.xlsx`

**Limitations:**
- **No server-side date filter** — UKRI API does not support filtering by date. Records are filtered client-side using the `created` epoch timestamp. Records with old start dates but a recent `created` date may be missed.
- Each matching record requires **3 secondary API calls** (institution, PI, fund) — slower than other sources.
- A `MAX_RECORDS=500` cap prevents runaway behaviour on bulk-import days. If the warning `Reached MAX_RECORDS limit` appears in the log, a bulk import likely occurred on that date.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success — output file saved |
| `1` | Failure — see console output and `error.log` |

---

## Log Files

Both log files are written to the `logs/` directory (created automatically):

- `logs/app.log` — full debug log for all runs
- `logs/error.log` — errors only, for quick diagnosis
