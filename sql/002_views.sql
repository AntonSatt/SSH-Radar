-- SSH Radar — Views & Aggregations
-- Provides convenient query interfaces for Grafana and the React frontend

BEGIN;

-- ============================================================
-- View: login_attempts_geo
-- Joins failed logins with geolocation data for easy querying
-- ============================================================
CREATE OR REPLACE VIEW login_attempts_geo AS
SELECT
    fl.id,
    fl.username,
    fl.source_ip,
    fl.timestamp,
    fl.terminal,
    fl.protocol,
    geo.country_code,
    geo.country,
    geo.city,
    geo.latitude,
    geo.longitude,
    geo.asn
FROM failed_logins fl
LEFT JOIN ip_geolocations geo ON fl.source_ip = geo.ip;


-- ============================================================
-- Materialized View: daily_stats
-- Pre-aggregated daily statistics for fast dashboard queries
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_stats AS
SELECT
    date_trunc('day', timestamp)::DATE   AS day,
    COUNT(*)                              AS total_attempts,
    COUNT(DISTINCT source_ip)             AS unique_ips,
    COUNT(DISTINCT username)              AS unique_usernames
FROM failed_logins
GROUP BY date_trunc('day', timestamp)::DATE
ORDER BY day DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_stats_day
    ON daily_stats (day);


-- ============================================================
-- Materialized View: monthly_stats
-- Pre-aggregated monthly statistics
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS monthly_stats AS
SELECT
    date_trunc('month', timestamp)::DATE AS month,
    COUNT(*)                              AS total_attempts,
    COUNT(DISTINCT source_ip)             AS unique_ips,
    COUNT(DISTINCT username)              AS unique_usernames
FROM failed_logins
GROUP BY date_trunc('month', timestamp)::DATE
ORDER BY month DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_monthly_stats_month
    ON monthly_stats (month);


-- ============================================================
-- Materialized View: country_stats
-- Attempts aggregated by country for the world map and pie chart
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS country_stats AS
SELECT
    geo.country_code,
    geo.country,
    COUNT(*)                              AS total_attempts,
    COUNT(DISTINCT fl.source_ip)          AS unique_ips,
    COUNT(DISTINCT fl.username)           AS unique_usernames
FROM failed_logins fl
JOIN ip_geolocations geo ON fl.source_ip = geo.ip
WHERE geo.country_code IS NOT NULL AND geo.country_code != 'XX'
GROUP BY geo.country_code, geo.country
ORDER BY total_attempts DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_country_stats_code
    ON country_stats (country_code);


-- ============================================================
-- Function: refresh_materialized_views()
-- Call after each ingestion run to update aggregations
-- ============================================================
CREATE OR REPLACE FUNCTION refresh_materialized_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY daily_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY monthly_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY country_stats;
END;
$$ LANGUAGE plpgsql;

COMMIT;
