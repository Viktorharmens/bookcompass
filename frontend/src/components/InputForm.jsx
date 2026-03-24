import { useState, useRef } from 'react'

const STEPS = ['Laag', 'Lager', 'Neutraal', 'Hoger', 'Hoog']
const EXAMPLE_URL = 'https://openlibrary.org/works/OL1168007W/Nineteen_Eighty-Four'

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
  const [url, setUrl]               = useState('')
  const [styleWeight, setStyleWeight] = useState(3)
  const [topicWeight, setTopicWeight] = useState(3)
  const inputRef = useRef(null)

  const isValid   = url.includes('openlibrary.org')
  const showError = url.length > 10 && !isValid

  function handleSubmit(e) {
    e.preventDefault()
    if (!isValid || loading) return
    inputRef.current?.blur()
    onSubmit({ url: url.trim(), styleWeight, topicWeight })
  }

  return (
    <form className="input-form" onSubmit={handleSubmit} noValidate>
      <div className="field-group">
        <label htmlFor="book-url">Open Library URL</label>
        <div className="input-wrapper">
          <svg className="input-icon" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
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
            onChange={e => setUrl(e.target.value)}
            className={`url-input${showError ? ' invalid' : ''}${url ? ' has-clear' : ''}`}
          />
          {url && (
            <button type="button" className="input-clear" onClick={() => { setUrl(''); inputRef.current?.focus() }} aria-label="Wis URL">
              <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
              </svg>
            </button>
          )}
        </div>
        {showError && <span className="field-error">Voer een openlibrary.org URL in</span>}
      </div>

      <hr className="form-divider" />

      <div className="sliders">
        <span className="slider-section-title">
          <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            <circle cx="7" cy="5" r="2" fill="white" stroke="currentColor" strokeWidth="1.6"/>
            <circle cx="13" cy="10" r="2" fill="white" stroke="currentColor" strokeWidth="1.6"/>
            <circle cx="7" cy="15" r="2" fill="white" stroke="currentColor" strokeWidth="1.6"/>
          </svg>
          Wegingen
        </span>
        <WeightSlider label="Schrijfstijl" value={styleWeight} onChange={setStyleWeight} />
        <WeightSlider label="Onderwerp"    value={topicWeight}  onChange={setTopicWeight} />
      </div>

      <button type="submit" className="submit-btn" disabled={!isValid || loading}>
        {loading ? 'Zoeken…' : 'Aanbevelingen genereren'}
        {!loading && <span className="submit-chevron">›</span>}
      </button>

      <p className="example-link">
        <a onClick={() => setUrl(EXAMPLE_URL)} role="button">
          Bekijk een voorbeeld →
        </a>
      </p>
    </form>
  )
}
