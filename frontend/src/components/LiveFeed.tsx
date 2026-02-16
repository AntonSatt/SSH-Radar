import { useState, useEffect, useRef } from 'react'
import './LiveFeed.css'

interface Attempt {
  timestamp: string
  username: string
  ip: string
  country: string
  city: string
}

function LiveFeed() {
  const [attempts, setAttempts] = useState<Attempt[]>([])
  const [newIds, setNewIds] = useState<Set<string>>(new Set())
  const listRef = useRef<HTMLDivElement>(null)
  const prevCountRef = useRef(0)

  useEffect(() => {
    const fetchAttempts = async () => {
      try {
        const response = await fetch('/grafana/api/ds/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            queries: [
              {
                refId: 'feed',
                datasource: { type: 'postgres', uid: 'ssh-radar-postgres' },
                rawSql: "SELECT TO_CHAR(f.timestamp, 'HH24:MI:SS') AS time, f.username, host(f.source_ip) AS ip, COALESCE(g.country, 'Unknown') AS country, COALESCE(g.city, '') AS city FROM failed_logins f LEFT JOIN ip_geolocations g ON f.source_ip = g.ip ORDER BY f.timestamp DESC LIMIT 50",
                format: 'table',
              },
            ],
            from: 'now-1h',
            to: 'now',
          }),
        })

        if (!response.ok) return

        const data = await response.json()
        const frames = data?.results?.feed?.frames
        if (frames && frames.length > 0) {
          const values = frames[0].data?.values
          if (values && values.length >= 5) {
            const rows: Attempt[] = values[0].map((_: string, i: number) => ({
              timestamp: values[0][i],
              username: values[1][i],
              ip: values[2][i],
              country: values[3][i],
              city: values[4][i],
            }))

            // Mark new entries that appeared since last fetch
            if (prevCountRef.current > 0 && rows.length > 0) {
              const fresh = new Set<string>()
              for (let i = 0; i < rows.length; i++) {
                const key = `${rows[i].timestamp}-${rows[i].ip}-${rows[i].username}`
                if (i < rows.length - prevCountRef.current + 5) {
                  fresh.add(key)
                }
              }
              setNewIds(fresh)
              setTimeout(() => setNewIds(new Set()), 3000)
            }

            prevCountRef.current = rows.length
            setAttempts(rows)
          }
        }
      } catch {
        // silently fail
      }
    }

    fetchAttempts()
    const interval = setInterval(fetchAttempts, 30_000)
    return () => clearInterval(interval)
  }, [])

  if (attempts.length === 0) return null

  return (
    <div className="live-feed">
      <div className="live-feed-header">
        <div className="live-feed-title">
          <span className="live-dot" />
          Live Feed
        </div>
        <span className="live-feed-subtitle">Recent failed login attempts</span>
      </div>
      <div className="live-feed-list" ref={listRef}>
        {attempts.map((a, i) => {
          const key = `${a.timestamp}-${a.ip}-${a.username}`
          const isNew = newIds.has(key)
          return (
            <div
              key={`${key}-${i}`}
              className={`live-feed-row ${isNew ? 'live-feed-row-new' : ''}`}
            >
              <span className="feed-time">{a.timestamp}</span>
              <span className="feed-separator">|</span>
              <span className="feed-user">{a.username}</span>
              <span className="feed-separator">@</span>
              <span className="feed-ip">{a.ip}</span>
              <span className="feed-location">
                {a.city && a.country ? `${a.city}, ${a.country}` : a.country}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default LiveFeed
