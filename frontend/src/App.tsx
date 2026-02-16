import Header from './components/Header'
import StatsBar from './components/StatsBar'
import DashboardEmbed from './components/DashboardEmbed'
import './App.css'

function App() {
  return (
    <div className="app">
      <Header />
      <main className="main">
        <StatsBar />
        <DashboardEmbed />
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
