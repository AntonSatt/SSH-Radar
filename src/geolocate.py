"""
IP Geolocation enrichment using MaxMind GeoLite2.

Looks up geographic data for IPs in the failed_logins table that don't
yet have entries in ip_geolocations, and batch-inserts the results.

Requires GeoLite2-City.mmdb — download with src/update_geodb.sh.
"""

import ipaddress
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import geoip2.database
import geoip2.errors

from config import get_db_connection, logger, MAXMIND_DB_PATH


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private/reserved (RFC 1918, loopback, etc.)."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local
    except ValueError:
        return False


def get_ungeolocated_ips() -> list[str]:
    """
    Get all unique source IPs from failed_logins that are not yet in ip_geolocations.

    Returns:
        List of IP address strings
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT fl.source_ip::TEXT
            FROM failed_logins fl
            LEFT JOIN ip_geolocations geo ON fl.source_ip = geo.ip
            WHERE fl.source_ip IS NOT NULL
              AND geo.ip IS NULL
        """)
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def lookup_ip(reader: geoip2.database.Reader, ip_str: str) -> dict:
    """
    Look up geolocation data for a single IP.

    Args:
        reader: GeoLite2 database reader
        ip_str: IP address string

    Returns:
        Dict with geolocation fields ready for DB insertion
    """
    result = {
        "ip": ip_str,
        "country_code": None,
        "country": None,
        "city": None,
        "latitude": None,
        "longitude": None,
        "asn": None,
    }

    # Handle private/reserved IPs
    if is_private_ip(ip_str):
        result["country_code"] = "XX"
        result["country"] = "Private"
        result["city"] = "Private Network"
        return result

    try:
        response = reader.city(ip_str)

        result["country_code"] = response.country.iso_code
        result["country"] = response.country.name
        result["city"] = response.city.name
        if response.location:
            result["latitude"] = response.location.latitude
            result["longitude"] = response.location.longitude

    except geoip2.errors.AddressNotFoundError:
        logger.debug("IP not found in GeoLite2 database: %s", ip_str)
        result["country_code"] = "XX"
        result["country"] = "Unknown"
    except Exception:
        logger.warning("Failed to look up IP: %s", ip_str, exc_info=True)
        result["country_code"] = "XX"
        result["country"] = "Lookup Failed"

    return result


def insert_geolocations(records: list[dict]) -> int:
    """
    Insert geolocation records into ip_geolocations table.

    Uses ON CONFLICT to update existing records if re-run.

    Args:
        records: List of geolocation dicts from lookup_ip()

    Returns:
        Number of records inserted/updated
    """
    if not records:
        return 0

    conn = get_db_connection()
    count = 0

    try:
        cur = conn.cursor()

        for rec in records:
            cur.execute(
                """
                INSERT INTO ip_geolocations (ip, country_code, country, city, latitude, longitude, asn)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ip) DO UPDATE SET
                    country_code = EXCLUDED.country_code,
                    country = EXCLUDED.country,
                    city = EXCLUDED.city,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    asn = EXCLUDED.asn,
                    last_updated = NOW()
                """,
                (
                    rec["ip"],
                    rec["country_code"],
                    rec["country"],
                    rec["city"],
                    rec["latitude"],
                    rec["longitude"],
                    rec["asn"],
                ),
            )
            count += 1

        conn.commit()
        logger.info("Inserted/updated %d geolocation records", count)

    except Exception:
        conn.rollback()
        logger.exception("Failed to insert geolocation records")
        raise
    finally:
        conn.close()

    return count


def enrich_new_ips() -> int:
    """
    Main entry point: find un-geolocated IPs, look them up, store results.

    Returns:
        Number of IPs enriched
    """
    # Verify GeoLite2 database exists
    db_path = os.path.abspath(MAXMIND_DB_PATH)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(
            f"GeoLite2 database not found at {db_path}. "
            f"Run src/update_geodb.sh to download it."
        )

    # Get IPs that need geolocation
    ips = get_ungeolocated_ips()
    if not ips:
        logger.info("No new IPs to geolocate")
        return 0

    logger.info("Geolocating %d new IPs...", len(ips))

    # Look them all up
    reader = geoip2.database.Reader(db_path)
    try:
        results = [lookup_ip(reader, ip) for ip in ips]
    finally:
        reader.close()

    # Store results
    return insert_geolocations(results)


if __name__ == "__main__":
    enriched = enrich_new_ips()
    print(f"Geolocated {enriched} IPs")
