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

const FETCH_INTERVAL = 60_000
const DELAY_SECONDS = 300 // 5 minute replay delay
const MAX_VISIBLE = 50

// Web Audio blip sound — combo raises pitch
function createBlipPlayer() {
  let ctx: AudioContext | null = null
  let combo = 0
  let lastBlipTime = 0

  return {
    play() {
      if (!ctx) ctx = new AudioContext()
      if (ctx.state === 'suspended') ctx.resume()

      const now = performance.now()
      if (now - lastBlipTime < 2000) {
        combo = Math.min(combo + 1, 8)
      } else {
        combo = 0
      }
      lastBlipTime = now

      const freq = 600 + combo * 80 // 600Hz base, up to ~1240Hz
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()

      osc.type = 'sine'
      osc.frequency.value = freq
      osc.connect(gain)
      gain.connect(ctx.destination)

      const t = ctx.currentTime
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.15, t + 0.005) // 5ms attack
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.08) // 75ms decay

      osc.start(t)
      osc.stop(t + 0.1)
    },
  }
}

function LiveFeed() {
  const [visible, setVisible] = useState<Attempt[]>([])
  const [expanded, setExpanded] = useState(true)
  const [soundEnabled, setSoundEnabled] = useState(false)
  const queueRef = useRef<Attempt[]>([]) // sorted by epoch ascending
  const seenRef = useRef<Set<string>>(new Set())
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isFirstFetch = useRef(true)
  const listRef = useRef<HTMLDivElement>(null)
  const blipRef = useRef(createBlipPlayer())
  const soundEnabledRef = useRef(false)

  // Keep ref in sync with state so the timeout callback sees the latest value
  useEffect(() => {
    soundEnabledRef.current = soundEnabled
  }, [soundEnabled])

  const makeKey = (a: Attempt) => `${a.epoch}-${a.ip}-${a.username}`

  // Schedule the next entry to appear at its real time + 5 min offset
  const scheduleNext = useCallback(() => {
    if (queueRef.current.length === 0) {
      timerRef.current = null
      return
    }

    const next = queueRef.current[0]
    const showAtMs = (next.epoch + DELAY_SECONDS) * 1000
    const waitMs = Math.max(0, showAtMs - Date.now())

    timerRef.current = setTimeout(() => {
      queueRef.current.shift()
      setVisible((prev) => [next, ...prev].slice(0, MAX_VISIBLE))

      if (soundEnabledRef.current) {
        blipRef.current.play()
      }

      scheduleNext()
    }, waitMs)
  }, [])

  // Insert entries into queue maintaining epoch ascending order
  const enqueue = useCallback(
    (entries: Attempt[]) => {
      if (entries.length === 0) return

      for (const entry of entries) {
        const key = makeKey(entry)
        if (seenRef.current.has(key)) continue
        seenRef.current.add(key)

        // Insert in sorted position (ascending by epoch)
        let idx = queueRef.current.length
        while (idx > 0 && queueRef.current[idx - 1].epoch > entry.epoch) {
          idx--
        }
        queueRef.current.splice(idx, 0, entry)
      }

      // If no timer running, start the scheduler
      if (!timerRef.current) {
        scheduleNext()
      }
    },
    [scheduleNext],
  )

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
                rawSql:
                  "SELECT EXTRACT(EPOCH FROM f.timestamp)::BIGINT AS epoch, f.username, host(f.source_ip) AS ip, COALESCE(g.country, 'Unknown') AS country, COALESCE(g.city, '') AS city FROM failed_logins f LEFT JOIN ip_geolocations g ON f.source_ip = g.ip ORDER BY f.timestamp DESC LIMIT 100",
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

        const nowSec = Date.now() / 1000

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
          isFirstFetch.current = false

          // Split into already-past-delay (show immediately) and pending (schedule)
          const ready: Attempt[] = []
          const pending: Attempt[] = []

          for (const row of rows) {
            const key = makeKey(row)
            if (seenRef.current.has(key)) continue
            seenRef.current.add(key)

            if (row.epoch + DELAY_SECONDS <= nowSec) {
              ready.push(row)
            } else {
              pending.push(row)
            }
          }

          // Show the most recent ready entries immediately (newest first)
          setVisible(ready.slice(0, MAX_VISIBLE))

          // Queue pending entries sorted by epoch ascending for real-time replay
          pending.sort((a, b) => a.epoch - b.epoch)
          queueRef.current = pending
          if (pending.length > 0) {
            scheduleNext()
          }
        } else {
          // Subsequent fetches: enqueue any new entries
          enqueue(rows)
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
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [scheduleNext, enqueue])

  if (visible.length === 0) return null

  return (
    <div className="live-feed">
      <div className="live-feed-header">
        <button className="live-feed-toggle-btn" onClick={() => setExpanded(!expanded)}>
          <div className="live-feed-title">
            <span className="live-dot" />
            Live Feed
            <span className="live-feed-subtitle">Failed login attempts (5 min delay)</span>
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
        <button
          className={`sound-toggle ${soundEnabled ? 'sound-toggle-on' : ''}`}
          onClick={() => setSoundEnabled(!soundEnabled)}
          title={soundEnabled ? 'Mute sound' : 'Enable sound'}
        >
          {soundEnabled ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
              <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
              <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
              <line x1="23" y1="9" x2="17" y2="15" />
              <line x1="17" y1="9" x2="23" y2="15" />
            </svg>
          )}
        </button>
      </div>
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
