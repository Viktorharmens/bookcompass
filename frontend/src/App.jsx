import { useState } from 'react'
import InputForm from './components/InputForm'
import ResultsList from './components/ResultsList'
import Footer from './components/Footer'
import logo from './assets/logo.png'
import './App.css'

export default function App() {
  const [results, setResults] = useState(null)
  const [queryBook, setQueryBook] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit({ url, styleWeight, selectedSubjects }) {
    setLoading(true)
    setError(null)

    try {
      const res = await fetch('/api/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, style_weight: styleWeight, topic_weight: 3, selected_subjects: selectedSubjects }),
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
      <main className="app-main">
        <div className="brand">
          <img src={logo} alt="BookCompass" className="brand-logo" />
          <p className="brand-tagline">Navigate by feel. Find your next book.</p>
        </div>

        <InputForm onSubmit={handleSubmit} onClear={() => { setResults(null); setQueryBook(null) }} loading={loading} />

        {error && <div className="error-box"><strong>Error:</strong> {error}</div>}

        {loading && (
          <div className="loading-card">
            <div className="spinner" />
            <p>Analyzing and searching…</p>
          </div>
        )}

        {results && <ResultsList books={results} queryBook={queryBook} />}
      </main>
      <Footer />
    </div>
  )
}
