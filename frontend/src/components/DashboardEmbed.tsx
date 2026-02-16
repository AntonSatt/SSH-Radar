import './DashboardEmbed.css'

// Grafana panel embed URLs using kiosk mode
// These embed individual panels from the provisioned dashboard
const GRAFANA_BASE = '/grafana/d-solo/ssh-radar-main/ssh-radar'
const DEFAULT_TIME = 'from=now-30d&to=now'

const PANELS = [
  {
    id: 7,
    title: 'Attack Origins',
    className: 'panel-wide panel-map',
  },
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
  return (
    <div className="dashboard-grid">
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
