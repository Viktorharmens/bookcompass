import { useState } from 'react'
import InputForm from './components/InputForm'
import ResultsList from './components/ResultsList'
import './App.css'

export default function App() {
  const [results, setResults] = useState(null)
  const [queryBook, setQueryBook] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit({ url, styleWeight, topicWeight }) {
    setLoading(true)
    setError(null)

    try {
      const res = await fetch('http://localhost:8000/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, style_weight: styleWeight, topic_weight: topicWeight }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setQueryBook(data.query_book)
      setResults(data.recommendations)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Boekaanbeveler</h1>
        <p className="subtitle">Vind boeken op stijl en thematiek</p>
      </header>

      <main className="app-main">
        <InputForm onSubmit={handleSubmit} loading={loading} />

        {error && <div className="error-box"><strong>Fout:</strong> {error}</div>}

        {loading && (
          <div className="loading-card">
            <div className="spinner" />
            <p>Analyseren en zoeken…</p>
          </div>
        )}

        {queryBook && (
          <div className="query-chip">
            {queryBook.cover_url
              ? <img src={queryBook.cover_url} alt={queryBook.title} className="query-chip-cover" />
              : <div className="query-chip-placeholder">📖</div>
            }
            <div className="query-chip-text">
              <p className="query-chip-label">Gezocht op</p>
              <p className="query-chip-title">{queryBook.title}</p>
              <p className="query-chip-author">{queryBook.author}</p>
            </div>
          </div>
        )}

        {results && <ResultsList books={results} />}
      </main>
    </div>
  )
}
