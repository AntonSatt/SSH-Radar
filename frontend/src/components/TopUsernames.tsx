import { useState, useEffect } from 'react'
import './TopUsernames.css'

interface UsernameEntry {
  username: string
  count: number
}

function TopUsernames() {
  const [entries, setEntries] = useState<UsernameEntry[]>([])

  useEffect(() => {
    const fetchTop = async () => {
      try {
        const response = await fetch('/grafana/api/ds/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            queries: [
              {
                refId: 'topUsers',
                datasource: { type: 'postgres', uid: 'ssh-radar-postgres' },
                rawSql:
                  'SELECT username, COUNT(*) AS cnt FROM failed_logins GROUP BY username ORDER BY cnt DESC LIMIT 10',
                format: 'table',
              },
            ],
            from: 'now-1h',
            to: 'now',
          }),
        })

        if (!response.ok) return

        const data = await response.json()
        const frames = data?.results?.topUsers?.frames
        if (!frames || frames.length === 0) return
        const values = frames[0].data?.values
        if (!values || values.length < 2) return

        const rows: UsernameEntry[] = values[0].map((_: string, i: number) => ({
          username: values[0][i],
          count: values[1][i],
        }))

        setEntries(rows)
      } catch {
        // silently fail
      }
    }

    fetchTop()
    const interval = setInterval(fetchTop, 120_000)
    return () => clearInterval(interval)
  }, [])

  if (entries.length === 0) return null

  const chips = entries.map((e, i) => (
    <span key={e.username} className="top-username-chip">
      <span className="top-username-rank">{i + 1}</span>
      <span className="top-username-name">{e.username}</span>
      <span className="top-username-count">{e.count.toLocaleString()}</span>
    </span>
  ))

  return (
    <div className="top-usernames">
      <span className="top-usernames-label">Top Targets</span>
      <div className="top-usernames-track">
        <div className="top-usernames-scroll">
          <div className="top-usernames-list">{chips}</div>
          <div className="top-usernames-list" aria-hidden="true">{chips}</div>
        </div>
      </div>
    </div>
  )
}

export default TopUsernames
