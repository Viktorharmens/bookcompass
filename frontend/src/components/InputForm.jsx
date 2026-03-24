import { useState, useRef } from 'react'

const STEPS = ['Niet belangrijk', 'Weinig', 'Neutraal', 'Belangrijk', 'Cruciaal']

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
        {STEPS.map((_, i) => (
          <span key={i} style={{ color: i + 1 === value ? '#4a3f6b' : undefined, fontWeight: i + 1 === value ? '700' : undefined }}>
            {i + 1}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function InputForm({ onSubmit, loading }) {
  const [url, setUrl] = useState('')
  const [styleWeight, setStyleWeight] = useState(3)
  const [topicWeight, setTopicWeight] = useState(3)
  const inputRef = useRef(null)

  const isValid = url.includes('openlibrary.org')
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
        <input
          ref={inputRef}
          id="book-url"
          type="url"
          inputMode="url"
          placeholder="https://openlibrary.org/works/…"
          value={url}
          onChange={e => setUrl(e.target.value)}
          className={`url-input${showError ? ' invalid' : ''}`}
        />
        {showError && <span className="field-error">Voer een openlibrary.org URL in</span>}
      </div>

      <div className="sliders">
        <span className="slider-section-title">Wegingen</span>
        <WeightSlider label="Schrijfstijl" value={styleWeight} onChange={setStyleWeight} />
        <WeightSlider label="Onderwerp" value={topicWeight} onChange={setTopicWeight} />
      </div>

      <button type="submit" className="submit-btn" disabled={!isValid || loading}>
        {loading ? 'Zoeken…' : 'Aanbevelingen genereren'}
      </button>
    </form>
  )
}
