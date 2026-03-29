# Government Grant Data Pipeline

Python-based data extraction system that pulls **research grant records from multiple public APIs**, handles pagination and normalization, and outputs **structured Excel files ready for downstream data pipelines**.

🔗 Repository: https://github.com/sachinks/api_grant

📁 Sample Outputs: See `sample_data/`

---

## 🚀 Key Features

- Full pagination support across all APIs  
- Date-based extraction (daily / weekly cadence)  
- Strict schema mapping (no deviation from required columns)  
- Robust error handling with retry logic  
- Structured Excel output (`.xlsx`) using pandas + openpyxl  
- Modular architecture for easy extension to new sources  
- CLI-based execution with optional `--date` override  

---

## 📊 Data Sources

| # | Source | API Endpoint | Cadence |
|---|--------|-------------|---------|
| 01 | NIH RePORTER | reporter.nih.gov/api | Daily |
| 02 | NSF Awards | api.nsf.gov/services/v1/awards | Daily |
| 03 | CORDIS (EU Grants) | cordis.europa.eu/api | Weekly |
| 04 | UKRI Gateway | gtr.ukri.org/api | Daily |

All APIs are public — no authentication required.

📁 See `sample_data/` for real output files generated from live APIs.

---

## 📁 Output Format

Each script produces:

SOURCE_YYYYMMDD.xlsx

Example:
NIH_20250110.xlsx

### Schema

| Column | Description |
|--------|-------------|
| FIRST | Investigator first name |
| LAST | Investigator last name |
| INSTITUTION | Awarding institution |
| TITLE | Grant title |
| FUNDING_AMT | Award amount |
| CURRENCY | Currency code (USD / EUR / GBP) |
| AWARD_DATE | Date award was issued |
| SOURCE | Data source name |
| LINK | Direct URL to grant record |

---

## ⚙️ Quick Start

```bash
git clone https://github.com/sachinks/api_grant.git
cd api_grant

python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

---

## ▶️ Usage

```bash
# Default (yesterday)
python scripts/nih_reporter.py

# Specific date
python scripts/nih_reporter.py --date 2025-01-15

# Debug mode
python scripts/nih_reporter.py --debug
```

Run all sources:

```bash
python scripts/nih_reporter.py
python scripts/nsf_awards.py
python scripts/cordis_eu.py
python scripts/ukri_gateway.py
```

---

## 🏗️ Project Structure

```
grant/
├── exceptions.py
├── requirements.txt
├── pytest.ini
├── .flake8
│
├── utils/
│   ├── logger.py
│   ├── retry.py
│   ├── timeit.py
│   └── excel.py
│
├── extractors/
│   ├── base.py
│   ├── nih.py
│   ├── nsf.py
│   ├── cordis.py
│   └── ukri.py
│
├── scripts/
│   ├── nih_reporter.py
│   ├── nsf_awards.py
│   ├── cordis_eu.py
│   └── ukri_gateway.py
│
└── tests/
    ├── conftest.py
    └── test_nih_extractor.py
```

---

## ⚠️ Known Limitations

### CORDIS (EU Grants)
- Geo-restricted in some environments (WSL/cloud IPs)
- PI names not available → FIRST/LAST empty
- Weekly data window (7 days)

### UKRI Gateway
- No server-side date filtering → client-side filtering required
- Requires multiple secondary API calls per record
- Some records may be missed due to sorting limitations
- `MAX_RECORDS` cap prevents runaway extraction

### NSF Awards
- Max 25 records per page
- Max 3,000 results per query

### General
- Default date = yesterday
- Run scripts from project root
- CORDIS should be run weekly

---

## 🧪 Testing

```bash
pytest
pytest -v
```

---

## 📝 Logging

Logs are written to:

| File | Description |
|------|-------------|
| logs/app.log | Full logs (DEBUG+) |
| logs/error.log | Errors only |

Use `--debug` for verbose console output.

---

## 📦 Dependencies

| Library | Purpose |
|---------|---------|
| requests | API calls |
| pandas | Data processing |
| openpyxl | Excel output |
| flake8 | Linting |
| pytest | Testing |
