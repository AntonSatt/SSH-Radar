import { useState, useEffect, useRef, useCallback } from 'react'
import './LiveFeed.css'

interface Attempt {
  timestamp: string
  epoch: number
  username: string
  ip: string
  country: string
  city: string
}

const FETCH_INTERVAL = 30_000
const MAX_VISIBLE = 50

function LiveFeed() {
  const [visible, setVisible] = useState<Attempt[]>([])
  const [expanded, setExpanded] = useState(true)
  const queueRef = useRef<Attempt[]>([])
  const seenRef = useRef<Set<string>>(new Set())
  const dripTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isFirstFetch = useRef(true)
  const listRef = useRef<HTMLDivElement>(null)

  const makeKey = (a: Attempt) => `${a.epoch}-${a.ip}-${a.username}`

  // Drip-feed: pop one entry from queue and prepend to visible list
  const dripNext = useCallback(() => {
    if (queueRef.current.length === 0) {
      dripTimerRef.current = null
      return
    }

    const next = queueRef.current.shift()!
    setVisible((prev) => {
      const updated = [next, ...prev]
      return updated.slice(0, MAX_VISIBLE)
    })

    // Schedule next drip with delay based on remaining queue size
    if (queueRef.current.length > 0) {
      // Spread remaining entries over the time until next fetch
      const delay = Math.max(800, FETCH_INTERVAL / (queueRef.current.length + 1))
      dripTimerRef.current = setTimeout(dripNext, Math.min(delay, 3000))
    } else {
      dripTimerRef.current = null
    }
  }, [])

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
                rawSql: "SELECT EXTRACT(EPOCH FROM f.timestamp)::BIGINT AS epoch, f.username, host(f.source_ip) AS ip, COALESCE(g.country, 'Unknown') AS country, COALESCE(g.city, '') AS city FROM failed_logins f LEFT JOIN ip_geolocations g ON f.source_ip = g.ip ORDER BY f.timestamp DESC LIMIT 50",
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
        if (!frames || frames.length === 0) return
        const values = frames[0].data?.values
        if (!values || values.length < 5) return

        const rows: Attempt[] = values[0].map((_: number, i: number) => {
          const epoch = values[0][i]
          const date = new Date(epoch * 1000)
          const local = date.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
          })
          return {
            timestamp: local,
            epoch,
            username: values[1][i],
            ip: values[2][i],
            country: values[3][i],
            city: values[4][i],
          }
        })

        if (isFirstFetch.current) {
          // On first load, show the most recent entries immediately,
          // then drip-feed the rest to create the streaming effect
          isFirstFetch.current = false
          const immediate = rows.slice(0, 5)
          const queued = rows.slice(5).reverse() // oldest first so they drip in order

          immediate.forEach((a) => seenRef.current.add(makeKey(a)))
          queued.forEach((a) => seenRef.current.add(makeKey(a)))

          setVisible(immediate)
          queueRef.current = queued
          if (queued.length > 0) {
            dripTimerRef.current = setTimeout(dripNext, 1200)
          }
        } else {
          // Subsequent fetches: find new entries not yet seen
          const newEntries: Attempt[] = []
          for (const row of rows) {
            const key = makeKey(row)
            if (!seenRef.current.has(key)) {
              newEntries.push(row)
              seenRef.current.add(key)
            }
          }

          if (newEntries.length > 0) {
            // Reverse so oldest drips in first, newest last (appears at top)
            queueRef.current.push(...newEntries.reverse())
            if (!dripTimerRef.current) {
              dripTimerRef.current = setTimeout(dripNext, 800)
            }
          }
        }

        // Keep seen set from growing too large
        if (seenRef.current.size > 500) {
          const arr = Array.from(seenRef.current)
          seenRef.current = new Set(arr.slice(arr.length - 200))
        }
      } catch {
        // silently fail
      }
    }

    fetchAttempts()
    const interval = setInterval(fetchAttempts, FETCH_INTERVAL)
    return () => {
      clearInterval(interval)
      if (dripTimerRef.current) clearTimeout(dripTimerRef.current)
    }
  }, [dripNext])

  if (visible.length === 0) return null

  return (
    <div className="live-feed">
      <button className="live-feed-header" onClick={() => setExpanded(!expanded)}>
        <div className="live-feed-title">
          <span className="live-dot" />
          Live Feed
          <span className="live-feed-subtitle">Recent failed login attempts (5 min delay)</span>
        </div>
        <svg
          className={`live-feed-toggle ${expanded ? 'live-feed-toggle-open' : ''}`}
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {expanded && (
        <div className="live-feed-list" ref={listRef}>
          {visible.map((a, i) => (
            <div
              key={`${makeKey(a)}-${i}`}
              className={`live-feed-row ${i === 0 ? 'live-feed-row-new' : ''}`}
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
          ))}
        </div>
      )}
    </div>
  )
}

export default LiveFeed
