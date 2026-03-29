import { useState, useRef, useCallback } from 'react'

const STEPS       = ['Low', 'Lower', 'Neutral', 'Higher', 'High']
const EXAMPLE_URL = 'https://openlibrary.org/works/OL1168007W/Nineteen_Eighty-Four'
const API         = '/api'

function WeightSlider({ label, value, onChange }) {
  return (
    <div className="slider-group">
      <div className="slider-header">
        <span className="slider-label">{label}</span>
        <span className="slider-pill">{STEPS[value - 1]}</span>
      </div>
      <input
        type="range" min="1" max="5" step="1"
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="slider"
      />
      <div className="slider-steps">
        {[1,2,3,4,5].map(i => (
          <span key={i} className={i === value ? 'step-active' : ''}>{i}</span>
        ))}
      </div>
    </div>
  )
}

export default function InputForm({ onSubmit, loading }) {
  const [url, setUrl]                       = useState('')
  const [styleWeight, setStyleWeight]       = useState(3)
  const [showStyle, setShowStyle]           = useState(false)
  const [bookInfo, setBookInfo]             = useState(null)
  const [selectedSubjects, setSelected]     = useState([])
  const [loadingInfo, setLoadingInfo]       = useState(false)
  const [infoError, setInfoError]           = useState(null)
  const inputRef  = useRef(null)
  const lastUrl   = useRef('')

  const isValid   = url.includes('openlibrary.org')
  const showError = url.length > 10 && !isValid

  const fetchBookInfo = useCallback(async (targetUrl) => {
    const clean = targetUrl.trim()
    if (!clean.includes('openlibrary.org') || clean === lastUrl.current) return
    lastUrl.current = clean
    setLoadingInfo(true)
    setInfoError(null)
    setBookInfo(null)
    setSelected([])
    try {
      const res = await fetch(`${API}/book-info`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: clean }),
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      setBookInfo(data)
    } catch {
      setInfoError('Could not fetch book info')
    } finally {
      setLoadingInfo(false)
    }
  }, [])

  function toggleSubject(subject) {
    setSelected(prev =>
      prev.includes(subject)
        ? prev.filter(s => s !== subject)
        : [...prev, subject]
    )
  }

  function handleUrlChange(e) {
    setUrl(e.target.value)
    if (bookInfo) {
      setBookInfo(null)
      setSelected([])
      lastUrl.current = ''
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!isValid || loading) return
    inputRef.current?.blur()
    onSubmit({ url: url.trim(), styleWeight, selectedSubjects })
  }

  return (
    <form className="input-form" onSubmit={handleSubmit} noValidate>
      <div className="field-group">
        <label htmlFor="book-url">
          Open Library URL
          <a href="https://openlibrary.org" target="_blank" rel="noopener noreferrer" className="label-link" tabIndex={-1}>
            <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M11 3h6v6M17 3l-8 8M8 5H4a1 1 0 00-1 1v10a1 1 0 001 1h10a1 1 0 001-1v-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </a>
        </label>
        <div className="input-wrapper">
          <svg className="input-icon" viewBox="0 0 20 20" fill="none">
            <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.8"/>
            <path d="M14 14l3 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
          </svg>
          <input
            ref={inputRef}
            id="book-url"
            type="url"
            inputMode="url"
            placeholder="https://openlibrary.org/works/..."
            value={url}
            onChange={handleUrlChange}
            onPaste={e => {
              const pasted = e.clipboardData.getData('text')
              setTimeout(() => fetchBookInfo(pasted), 0)
            }}
            className={`url-input${showError ? ' invalid' : ''}${url ? ' has-clear' : ''}`}
          />
          {url && (
            <button type="button" className="input-clear"
              onClick={() => { setUrl(''); setBookInfo(null); setSelected([]); lastUrl.current = ''; inputRef.current?.focus() }}
              aria-label="Clear URL">
              <svg viewBox="0 0 20 20" fill="none">
                <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
              </svg>
            </button>
          )}
        </div>
        {showError && <span className="field-error">Please enter an openlibrary.org URL</span>}
      </div>

      {loadingInfo && (
        <div className="tag-loading">
          <span className="tag-loading-spinner" />
          <span>Fetching book info…</span>
        </div>
      )}

      {bookInfo && bookInfo.subjects.length > 0 && (
        <div className="subject-picker">
          <p className="subject-picker-label">
            What appeals to you about <strong>{bookInfo.title}</strong>?
            <span className="subject-picker-hint"> Click to select</span>
          </p>
          <div className="subject-tags">
            {bookInfo.subjects.map(s => (
              <button
                key={s}
                type="button"
                className={`subject-tag${selectedSubjects.includes(s) ? ' selected' : ''}`}
                onClick={() => toggleSubject(s)}
              >
                {s}
              </button>
            ))}
          </div>
          {selectedSubjects.length > 0 && (
            <p className="subject-picker-count">
              {selectedSubjects.length} theme{selectedSubjects.length !== 1 ? 's' : ''} selected
            </p>
          )}
        </div>
      )}

      {infoError && <p className="field-error">{infoError}</p>}

      <hr className="form-divider" />

      <button type="button" className="style-toggle" onClick={() => setShowStyle(s => !s)}>
        <svg viewBox="0 0 20 20" fill="none">
          <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
          <circle cx="7" cy="5" r="2" fill="white" stroke="currentColor" strokeWidth="1.6"/>
          <circle cx="13" cy="10" r="2" fill="white" stroke="currentColor" strokeWidth="1.6"/>
          <circle cx="7" cy="15" r="2" fill="white" stroke="currentColor" strokeWidth="1.6"/>
        </svg>
        Writing style
        <svg className={`toggle-chevron${showStyle ? ' open' : ''}`} viewBox="0 0 20 20" fill="none">
          <path d="M5 8l5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>
      {showStyle && (
        <div className="style-panel">
          <WeightSlider label="Writing style" value={styleWeight} onChange={setStyleWeight} />
        </div>
      )}

      <button type="submit" className="submit-btn" disabled={!isValid || loading}>
        {loading ? 'Searching…' : 'Get recommendations'}
        {!loading && <span className="submit-chevron">›</span>}
      </button>

      <p className="example-link">
        <a onClick={() => { setUrl(EXAMPLE_URL); setBookInfo(null); setSelected([]); lastUrl.current = '' }} role="button">
          View an example →
        </a>
      </p>
    </form>
  )
}
