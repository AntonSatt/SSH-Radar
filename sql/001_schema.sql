-- SSH Radar — Database Schema
-- Tracks failed login attempts parsed from lastb output

BEGIN;

-- ============================================================
-- Table: failed_logins
-- Stores every failed login attempt from lastb
-- ============================================================
CREATE TABLE IF NOT EXISTS failed_logins (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(64)     NOT NULL,
    source_ip       INET,                       -- NULL if no IP (e.g. local console)
    timestamp       TIMESTAMPTZ     NOT NULL,
    terminal        VARCHAR(64),
    protocol        VARCHAR(16),                -- ssh, console, etc.
    raw_line        TEXT,                        -- original lastb line for debugging
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Deduplication: same user + IP + timestamp = same event
    -- NULLS NOT DISTINCT ensures console logins (source_ip=NULL) are also deduplicated
    CONSTRAINT uq_failed_login UNIQUE NULLS NOT DISTINCT (username, source_ip, timestamp)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_failed_logins_timestamp
    ON failed_logins (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_failed_logins_source_ip
    ON failed_logins (source_ip);

CREATE INDEX IF NOT EXISTS idx_failed_logins_username
    ON failed_logins (username);

-- Composite index for time-range + IP queries (Grafana panels)
CREATE INDEX IF NOT EXISTS idx_failed_logins_ts_ip
    ON failed_logins (timestamp DESC, source_ip);


-- ============================================================
-- Table: ip_geolocations
-- Caches geolocation data for each unique source IP
-- ============================================================
CREATE TABLE IF NOT EXISTS ip_geolocations (
    ip              INET            PRIMARY KEY,
    country_code    CHAR(2),                    -- ISO 3166-1 alpha-2 (e.g. 'SE', 'US')
    country         VARCHAR(64),
    city            VARCHAR(128),
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    asn             VARCHAR(128),
    last_updated    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ip_geo_country_code
    ON ip_geolocations (country_code);

COMMIT;
