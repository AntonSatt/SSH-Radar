import './Header.css'

interface HeaderProps {
  page: string
  setPage: (page: string) => void
}

function Header({ page, setPage }: HeaderProps) {
  const navigate = (e: React.MouseEvent, target: string, path: string) => {
    e.preventDefault()
    window.history.pushState(null, '', path)
    setPage(target)
  }

  return (
    <header className="header">
      <div className="header-content">
        <div className="header-left">
          <a
            href="/"
            className="header-brand"
            onClick={(e) => navigate(e, 'home', '/')}
          >
            <div className="header-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </div>
            <div>
              <h1 className="header-title">SSH Radar</h1>
              <p className="header-subtitle">Real-time failed SSH login analytics with IP geolocation</p>
            </div>
          </a>
        </div>
        <nav className="header-nav">
          <a
            href="/about"
            className={`header-link ${page === 'about' ? 'header-link-active' : ''}`}
            onClick={(e) => navigate(e, 'about', '/about')}
          >
            About
          </a>
          <a href="/grafana/d/ssh-radar-main/ssh-radar" className="header-link">
            Full Dashboard
          </a>
          <a href="https://antonsatt.com" target="_blank" rel="noopener noreferrer" className="header-link">
            antonsatt.com
          </a>
          <a href="https://github.com/antonsatt/ssh-radar" target="_blank" rel="noopener noreferrer" className="header-link header-link-github">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
            </svg>
            GitHub
          </a>
        </nav>
      </div>
    </header>
  )
}

export default Header
