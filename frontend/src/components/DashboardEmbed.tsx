import { useState } from 'react'
import './DashboardEmbed.css'

// Grafana panel embed URLs using kiosk mode
// These embed individual panels from the provisioned dashboard
const GRAFANA_BASE = '/grafana/d-solo/ssh-radar-main/ssh-radar'
const DEFAULT_TIME = 'from=now-30d&to=now'

const PANELS = [
  {
    id: 5,
    title: 'Daily Trend',
    className: 'panel-half',
  },
  {
    id: 6,
    title: 'Hourly (24h)',
    className: 'panel-half',
    time: 'from=now-24h&to=now',
  },
  {
    id: 9,
    title: 'Top IPs',
    className: 'panel-half',
  },
  {
    id: 10,
    title: 'Top Usernames',
    className: 'panel-half',
  },
  {
    id: 8,
    title: 'Attempts by Country',
    className: 'panel-half panel-pie',
  },
  {
    id: 12,
    title: 'Unique IPs by Country',
    className: 'panel-half panel-pie',
  },
  {
    id: 11,
    title: 'Recent Attempts',
    className: 'panel-wide',
  },
]

function DashboardEmbed() {
  const [mapExpanded, setMapExpanded] = useState(false)

  return (
    <div className="dashboard-grid">
      <div className={`dashboard-panel panel-wide panel-map ${mapExpanded ? 'panel-map-expanded' : 'panel-map-collapsed'}`}>
        <button
          className="panel-title panel-toggle"
          onClick={() => setMapExpanded(!mapExpanded)}
        >
          Attack Origins — World Map
          <svg
            className={`panel-toggle-icon ${mapExpanded ? 'panel-toggle-open' : ''}`}
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
        {mapExpanded && (
          <iframe
            src={`${GRAFANA_BASE}?orgId=1&panelId=7&theme=dark&kiosk&${DEFAULT_TIME}`}
            frameBorder="0"
            className="panel-iframe"
            title="Attack Origins"
          />
        )}
      </div>

      {PANELS.map((panel) => (
        <div key={panel.id} className={`dashboard-panel ${panel.className}`}>
          <h3 className="panel-title">{panel.title}</h3>
          <iframe
            src={`${GRAFANA_BASE}?orgId=1&panelId=${panel.id}&theme=dark&kiosk&${panel.time ?? DEFAULT_TIME}`}
            frameBorder="0"
            className="panel-iframe"
            title={panel.title}
            loading="lazy"
          />
        </div>
      ))}
    </div>
  )
}

export default DashboardEmbed
