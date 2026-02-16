# SSH Radar — Implementation Plan

## Tech Stack

| Component      | Choice                              |
|----------------|-------------------------------------|
| Language       | Python 3                            |
| Database       | PostgreSQL (Docker)                 |
| Geolocation    | MaxMind GeoLite2 (offline)          |
| Visualization  | Grafana (anonymous public access)   |
| Frontend       | React wrapper (branded landing page)|
| Reverse Proxy  | Nginx (host-level, already running) |
| Deployment     | Docker Compose on Oracle Free Tier  |
| Scheduling     | Cron on host (triggers ingestion)   |

## Target Environment

- Oracle Free Tier: Ubuntu ARM, 12GB RAM, 2 CPU, 100GB storage
- Public URL: ssh-radar.antonsatt.com
- Grafana anonymous viewer access for public dashboards
- PostgreSQL + ingestion internals not exposed to internet
- Nginx already running on host — used as reverse proxy

## File Structure

```
ssh-radar/
├── docker-compose.yml
├── nginx/
│   └── ssh-radar.conf
├── .env.example
├── requirements.txt
├── sql/
│   ├── 001_schema.sql
│   └── 002_views.sql
├── src/
│   ├── parser.py            # lastb output parser
│   ├── ingest.py            # ingestion pipeline entry point
│   ├── geolocate.py         # MaxMind GeoLite2 enrichment
│   ├── config.py            # DB connection, settings
│   └── update_geodb.sh      # download/refresh GeoLite2 DB
├── scripts/
│   └── run_ingest.sh        # host cron runner script
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── postgres.yml
│   │   └── dashboards/
│   │       └── dashboard.yml
│   └── dashboards/
│       └── ssh-radar.json
├── frontend/
│   ├── package.json
│   ├── index.html           # Vite entry point
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── App.css
│   │   ├── main.tsx
│   │   └── components/
│   │       ├── Header.tsx
│   │       ├── Header.css
│   │       ├── StatsBar.tsx
│   │       ├── StatsBar.css
│   │       ├── DashboardEmbed.tsx
│   │       └── DashboardEmbed.css
│   ├── Dockerfile
│   └── nginx.conf
├── tests/
│   ├── test_parser.py
│   ├── test_geolocate.py
│   ├── test_integration.py
│   └── fixtures/
│       └── sample_lastb.txt
└── README.md
```

---

## Phase 1: Schema & Parser

- [x] **1.1** Write `sql/001_schema.sql`
  - `failed_logins` table: `id SERIAL PRIMARY KEY`, `username VARCHAR(64)`, `source_ip INET`, `timestamp TIMESTAMPTZ`, `terminal VARCHAR(64)`, `protocol VARCHAR(16)`, `raw_line TEXT`, `created_at TIMESTAMPTZ DEFAULT NOW()`
  - `ip_geolocations` table: `ip INET PRIMARY KEY`, `country_code CHAR(2)`, `country VARCHAR(64)`, `city VARCHAR(128)`, `latitude DOUBLE PRECISION`, `longitude DOUBLE PRECISION`, `asn VARCHAR(128)`, `last_updated TIMESTAMPTZ DEFAULT NOW()`
  - Indexes on `failed_logins(timestamp)`, `failed_logins(source_ip)`, `failed_logins(username)`
  - Unique constraint on `failed_logins(username, source_ip, timestamp)` for deduplication (`NULLS NOT DISTINCT` for console logins with no IP)

- [x] **1.2** Write `sql/002_views.sql`
  - View `login_attempts_geo`: join `failed_logins` with `ip_geolocations` on `source_ip = ip`
  - Materialized view `daily_stats`: attempts per day, unique IPs, unique usernames
  - Materialized view `monthly_stats`: same aggregated by month
  - Materialized view `country_stats`: attempts aggregated by country (excludes private IPs)
  - Refresh function or note that materialized views are refreshed after each ingestion

- [x] **1.3** Write `src/parser.py`
  - Parse `lastb -F` output line by line
  - Extract: username, terminal, source_ip, timestamp (parse to datetime), protocol (infer from terminal: ssh, console, etc.)
  - Handle edge cases: IPv6 addresses, `still logged in` entries, `boot`/`reboot` lines (skip), blank source IP, lines with missing fields
  - Return list of dicts ready for DB insertion
  - Store raw line for debugging

- [x] **1.4** Write `tests/fixtures/sample_lastb.txt` with representative sample data
  - Include: normal SSH failures, IPv6 entries, entries with no IP, boot lines, varied timestamp formats

- [x] **1.5** Write `tests/test_parser.py`
  - Test normal SSH login parsing
  - Test IPv6 address handling
  - Test skipping of boot/reboot lines
  - Test handling of missing source IP
  - Test timestamp parsing accuracy

## Phase 2: Ingestion Pipeline

- [x] **2.1** Write `src/config.py`
  - Read from environment variables: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `MAXMIND_DB_PATH`
  - Provide sensible defaults for local development
  - Database connection helper using `psycopg2`

- [x] **2.2** Write `src/ingest.py`
  - Run `lastb -F` via subprocess (or read from stdin for testing)
  - Pipe output through parser
  - Connect to PostgreSQL, use `ON CONFLICT DO NOTHING` for deduplication
  - Bulk insert using `executemany` or `copy_from` for performance
  - After insertion, trigger geolocation enrichment for new IPs
  - After enrichment, refresh materialized views
  - Log summary: X new records inserted, Y IPs geolocated

- [x] **2.3** Write `requirements.txt`
  - `psycopg2-binary`, `geoip2`, `python-dotenv`, `pytest`

## Phase 3: Geolocation Enrichment

- [x] **3.1** Write `src/geolocate.py`
  - Query `failed_logins` for distinct `source_ip` values not present in `ip_geolocations`
  - Use `geoip2.database.Reader` with GeoLite2-City.mmdb
  - For each IP: look up country, city, lat/lon, ASN
  - Handle private/reserved IPs: mark as `country = 'Private'`, `country_code = 'XX'`
  - Handle lookup failures gracefully (unknown IPs)
  - Batch insert results into `ip_geolocations`

- [x] **3.2** Write `src/update_geodb.sh`
  - Download GeoLite2-City.mmdb from MaxMind using license key from env
  - Extract and place in known path (`/data/GeoLite2-City.mmdb` or configurable)
  - Can be run manually or via cron (MaxMind updates weekly on Tuesdays)

- [x] **3.3** Write `tests/test_geolocate.py`
  - Test private IP handling (10.x, 192.168.x, 172.16.x)
  - Test known public IP lookup (if GeoLite2 DB available)
  - Test graceful handling of unknown IPs

## Phase 4: Docker Compose & Deployment

- [x] **4.1** Write `docker-compose.yml`
  - **postgres**: PostgreSQL 16, volume `pgdata`, init scripts mounted from `sql/`, port `127.0.0.1:5432:5432` (localhost only)
  - **grafana**: Grafana OSS latest, provisioning dirs mounted, anonymous auth enabled via env vars, port `127.0.0.1:3000:3000`
  - **frontend**: React app built and served by Nginx, port `127.0.0.1:8080:80`
  - No reverse proxy container — Nginx runs on the host
  - Shared Docker network for internal communication
  - Health checks on postgres and grafana

- [x] **4.2** Write `.env.example`
  - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
  - `MAXMIND_LICENSE_KEY`
  - `DOMAIN` (e.g., `ssh-radar.antonsatt.com`)
  - `GF_SECURITY_ADMIN_PASSWORD`

- [x] **4.3** Write `nginx/ssh-radar.conf`
  - Host-level Nginx site config (replaces Caddy)
  - `/grafana/` → proxy_pass to `127.0.0.1:3000`
  - `/` → proxy_pass to `127.0.0.1:8080`
  - HTTPS via Certbot/Let's Encrypt
  - WebSocket support for Grafana Live

- [x] **4.4** Write cron job documentation/script
  - Host-level cron: `*/5 * * * * /path/to/run_ingest.sh`
  - `run_ingest.sh`: runs `lastb -F` on host, pipes to `docker exec` or runs Python directly on host connecting to Dockerized PostgreSQL
  - Note: `lastb` requires root, so cron runs as root

## Phase 5: Grafana Dashboard

- [x] **5.1** Write `grafana/provisioning/datasources/postgres.yml`
  - PostgreSQL datasource pointing to `postgres:5432` (Docker internal)
  - Database name, user, password from env
  - SSL mode disabled (internal network)

- [x] **5.2** Write `grafana/provisioning/dashboards/dashboard.yml`
  - Dashboard provisioning config pointing to `/var/lib/grafana/dashboards/`

- [x] **5.3** Build and export `grafana/dashboards/ssh-radar.json`
  - **Row 1 — Overview stats**:
    - Stat: Total attempts (all time)
    - Stat: Attempts today
    - Stat: Unique IPs today
    - Stat: Unique countries today
  - **Row 2 — Time series**:
    - Line chart: failed logins per day (last 30 days)
    - Line chart: failed logins per hour (last 24 hours)
  - **Row 3 — Geography**:
    - Geomap panel: world map with proportional circle markers by lat/lon, sized by attempt count
    - Pie chart: top 10 countries by attempt count
  - **Row 4 — Top attackers**:
    - Bar gauge: top 10 source IPs
    - Bar gauge: top 10 targeted usernames
  - **Row 5 — Detail**:
    - Table: last 100 failed login attempts with columns (timestamp, username, source_ip, country, city)
  - **Variables**:
    - Time range picker (built-in)
    - Country filter dropdown (populated from `ip_geolocations`)

- [x] **5.4** Configure Grafana anonymous access
  - `GF_AUTH_ANONYMOUS_ENABLED=true`
  - `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer`
  - `GF_SERVER_ROOT_URL=https://{DOMAIN}/grafana/`
  - `GF_SERVER_SERVE_FROM_SUB_PATH=true`

## Phase 6: React Frontend

- [x] **6.1** Scaffold React app with Vite + TypeScript
  - `npm create vite@latest frontend -- --template react-ts`
  - Clean up boilerplate

- [x] **6.2** Build `Header` component
  - Project title, brief description
  - Link back to antonsatt.com
  - GitHub repo link

- [x] **6.3** Build `StatsBar` component
  - Fetch headline stats from Grafana API (or a small Python API endpoint)
  - Display: total attacks, unique IPs, countries, attempts today
  - Auto-refresh every 60 seconds

- [x] **6.4** Build `DashboardEmbed` component
  - Embed Grafana panels via iframe using `&kiosk` mode URLs
  - Responsive layout — panels stack on mobile
  - Loading states while iframes load

- [x] **6.5** Write `frontend/Dockerfile`
  - Multi-stage: Stage 1 builds with Node, Stage 2 serves with Nginx
  - Copy built assets to Nginx html directory

- [x] **6.6** Write `frontend/nginx.conf`
  - Serve static files, SPA fallback (`try_files $uri /index.html`)

## Phase 7: Security Hardening

- [x] **7.1** PostgreSQL: only bound to `127.0.0.1` or Docker internal network, never exposed publicly
- [x] **7.2** Grafana: anonymous access = Viewer only, admin requires password login
- [x] **7.3** Nginx: HTTPS via Certbot, HTTP → HTTPS redirect
- [ ] **7.4** Oracle Cloud security list: only ports 80 and 443 open inbound
- [x] **7.5** No secrets in git — `.env` in `.gitignore`, `.env.example` committed
- [x] **7.6** Docker containers run as non-root where possible
- [x] **7.7** Rate limiting on Nginx (deferred — not yet needed for a portfolio project with low traffic)

## Phase 8: Testing & Documentation

- [x] **8.1** All unit tests pass (`pytest tests/`)
- [x] **8.2** Integration test: feed `sample_lastb.txt` through full pipeline, verify records in DB and geolocations populated
- [x] **8.3** Write `README.md`
  - Project description and motivation
  - Architecture diagram (text-based or image)
  - Setup instructions (clone, `.env`, `docker compose up`)
  - Screenshots of dashboard
  - Link to live instance
- [ ] **8.4** Add project to antonsatt.com portfolio with live link and description

---

## Notes for LLM Continuation

- **Current status**: Phases 1-8 code-complete (7.4 is manual on Oracle Cloud, 8.4 is manual portfolio update). Integration test written and passing.
- **Working directory**: `/home/kaffe/Documents/github_projects/login-tracker/` (repo name: `ssh-radar`)
- **When picking up**: Read this file, find the first unchecked `- [ ]` item, and start there.
- **When completing a task**: Change `- [ ]` to `- [x]` for that item before moving to the next.
- **All tests pass**: Run `python3 -m pytest tests/ -v` to verify (45 collected: 42 passed, 3 skipped without GeoLite2 DB). Integration tests (10) require Docker.
- **Note**: `python-dotenv` is listed in `requirements.txt` but not used in code. Environment variables are loaded by `scripts/run_ingest.sh` via `source .env` instead. Keep the dependency for potential future use or remove it to stay lean.
- **Important design decisions already made**:
  - Ingestion runs on the HOST (not in Docker) because `lastb` needs `/var/log/btmp` access
  - PostgreSQL port only exposed on localhost (`127.0.0.1:5432`) for the host-based ingestion script
  - Grafana served under `/grafana` subpath, React frontend at root `/`
  - MaxMind GeoLite2 for offline geolocation (requires free license key)
  - Caddy was replaced with host-level Nginx (already running on Oracle server)
  - Nginx config at `nginx/ssh-radar.conf`, HTTPS via Certbot
  - Docker containers expose ports on `127.0.0.1` only (3000 for Grafana, 8080 for frontend)
- **Remaining work**:
  - 7.4: Configure Oracle Cloud security list (manual, not code)
  - 8.4: Add to portfolio (manual)
- **To deploy**:
  1. Clone repo to Oracle server
  2. Copy `.env.example` to `.env`, fill in real values
  3. Run `bash src/update_geodb.sh` to download GeoLite2 DB
   4. Create venv and install Python deps on host: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
  5. Run `docker compose up -d`
  6. Copy Nginx config: `sudo cp nginx/ssh-radar.conf /etc/nginx/sites-available/ssh-radar`
  7. Enable site: `sudo ln -s /etc/nginx/sites-available/ssh-radar /etc/nginx/sites-enabled/`
  8. Get SSL cert: `sudo certbot --nginx -d ssh-radar.antonsatt.com`
  9. Reload Nginx: `sudo systemctl reload nginx`
  10. Set up cron: `sudo crontab -e` → `*/5 * * * * /opt/ssh-radar/scripts/run_ingest.sh >> /var/log/ssh-radar-ingest.log 2>&1`

