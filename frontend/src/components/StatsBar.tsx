import { useState, useEffect } from 'react'
import './StatsBar.css'

interface Stats {
  totalAttempts: number
  attemptsToday: number
  uniqueIps: number
  countries: number
}

function StatsBar() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    const fetchStats = async () => {
      try {
        // Fetch from Grafana's query API using the provisioned datasource
        // This hits the Grafana backend which proxies to PostgreSQL
        const response = await fetch('/grafana/api/ds/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            queries: [
              {
                refId: 'stats',
                datasource: { type: 'postgres', uid: 'ssh-radar-postgres' },
                rawSql: `SELECT 
                  (SELECT COUNT(*) FROM failed_logins) AS total_attempts,
                  (SELECT COUNT(*) FROM failed_logins WHERE timestamp >= CURRENT_DATE) AS attempts_today,
                  (SELECT COUNT(DISTINCT source_ip) FROM failed_logins) AS unique_ips,
                  (SELECT COUNT(DISTINCT country_code) FROM ip_geolocations WHERE country_code != 'XX') AS countries`,
                format: 'table',
              },
            ],
            from: 'now-1h',
            to: 'now',
          }),
        })

        if (!response.ok) throw new Error('Failed to fetch stats')

        const data = await response.json()
        const frames = data?.results?.stats?.frames
        if (frames && frames.length > 0) {
          const values = frames[0].data?.values
          if (values && values.length >= 4) {
            setStats({
              totalAttempts: values[0]?.[0] ?? 0,
              attemptsToday: values[1]?.[0] ?? 0,
              uniqueIps: values[2]?.[0] ?? 0,
              countries: values[3]?.[0] ?? 0,
            })
          }
        }
        setError(false)
      } catch {
        setError(true)
      }
    }

    fetchStats()
    const interval = setInterval(fetchStats, 60_000) // refresh every 60s
    return () => clearInterval(interval)
  }, [])

  if (error) {
    return (
      <div className="stats-bar stats-bar-error">
        <p>Could not load live stats. View the <a href="/grafana">full dashboard</a> instead.</p>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="stats-bar stats-bar-loading">
        <div className="stat-card skeleton" />
        <div className="stat-card skeleton" />
        <div className="stat-card skeleton" />
        <div className="stat-card skeleton" />
      </div>
    )
  }

  return (
    <div className="stats-bar">
      <StatCard label="Total Attempts" value={stats.totalAttempts} color="blue" />
      <StatCard label="Today" value={stats.attemptsToday} color="orange" />
      <StatCard label="Unique IPs" value={stats.uniqueIps} color="red" />
      <StatCard label="Countries" value={stats.countries} color="green" />
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className={`stat-card stat-card-${color}`}>
      <span className="stat-value">{value.toLocaleString()}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}

export default StatsBar
