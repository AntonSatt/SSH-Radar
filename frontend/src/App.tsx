import { useState, useEffect } from 'react'
import Header from './components/Header'
import StatsBar from './components/StatsBar'
import DashboardEmbed from './components/DashboardEmbed'
import About from './components/About'
import './App.css'

function getPage() {
  return window.location.pathname === '/about' ? 'about' : 'home'
}

function App() {
  const [page, setPage] = useState(getPage)

  useEffect(() => {
    const onPopState = () => setPage(getPage())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  return (
    <div className="app">
      <Header page={page} setPage={setPage} />
      <main className="main">
        {page === 'about' ? (
          <About />
        ) : (
          <>
            <StatsBar />
            <DashboardEmbed />
          </>
        )}
      </main>
      <footer className="footer">
        <p>
          Built by{' '}
          <a href="https://antonsatt.com" target="_blank" rel="noopener noreferrer">
            Anton Sätterkvist
          </a>
          {' | '}
          <a href="https://github.com/antonsatt/ssh-radar" target="_blank" rel="noopener noreferrer">
            Source Code
          </a>
        </p>
      </footer>
    </div>
  )
}

export default App
