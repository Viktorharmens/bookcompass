import { useState, useRef, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

const API = '/api'

function FocusSlider({ value, onChange }) {
  const { t } = useTranslation()
  return (
    <div className="slider-group">
      <div className="slider-endpoints">
        <span className={`slider-endpoint${value <= 2 ? ' active' : ''}`}>{t('form.sliderTopic')}</span>
        <span className={`slider-endpoint${value >= 4 ? ' active' : ''}`}>{t('form.sliderStyle')}</span>
      </div>
      <input
        type="range" min="1" max="5" step="1"
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="slider"
      />
    </div>
  )
}

export default function InputForm({ onSubmit, onClear, loading }) {
  const { t } = useTranslation()
  const [query, setQuery]                    = useState('')
  const [styleWeight, setStyleWeight]        = useState(3)
  const [bookInfo, setBookInfo]              = useState(null)
  const [selectedSubjects, setSelected]      = useState([])
  const [loadingInfo, setLoadingInfo]        = useState(false)
  const [infoError, setInfoError]            = useState(null)
  const inputRef = useRef(null)
  const lastQuery = useRef('')
  const debounceRef = useRef(null)

  const isValid = query.trim().length > 2 && !loadingInfo

  const fetchBookInfo = useCallback(async (text) => {
    const clean = text.trim()
    if (clean.length < 3 || clean === lastQuery.current) return
    lastQuery.current = clean
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
      setInfoError(t('form.infoError'))
    } finally {
      setLoadingInfo(false)
    }
  }, [t])

  // Debounce: fetch book info 600ms after last keystroke
  useEffect(() => {
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchBookInfo(query), 600)
    return () => clearTimeout(debounceRef.current)
  }, [query, fetchBookInfo])

  function toggleSubject(subject) {
    setSelected(prev =>
      prev.includes(subject)
        ? prev.filter(s => s !== subject)
        : [...prev, subject]
    )
  }

  function handleQueryChange(e) {
    setQuery(e.target.value)
    if (bookInfo) {
      setBookInfo(null)
      setSelected([])
      lastQuery.current = ''
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!isValid || loading) return
    inputRef.current?.blur()
    onSubmit({ url: query.trim(), styleWeight, selectedSubjects })
  }

  return (
    <form className="input-form" onSubmit={handleSubmit} noValidate>
      <div className="field-group">
        <label htmlFor="book-query">
          {t('form.label')}
        </label>
        <div className="input-wrapper">
          <svg className="input-icon" viewBox="0 0 20 20" fill="none">
            <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.8"/>
            <path d="M14 14l3 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
          </svg>
          <input
            ref={inputRef}
            id="book-query"
            type="text"
            placeholder={t('form.placeholder')}
            value={query}
            onChange={handleQueryChange}
            onPaste={e => {
              const pasted = e.clipboardData.getData('text')
              clearTimeout(debounceRef.current)
              setTimeout(() => fetchBookInfo(pasted), 0)
            }}
            className={`url-input${query ? ' has-clear' : ''}`}
          />
          {query && (
            <button type="button" className="input-clear"
              onClick={() => {
                setQuery('')
                setBookInfo(null)
                setSelected([])
                lastQuery.current = ''
                onClear?.()
                inputRef.current?.focus()
              }}
              aria-label="Clear">
              <svg viewBox="0 0 20 20" fill="none">
                <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      {loadingInfo && (
        <div className="tag-loading">
          <span className="tag-loading-spinner" />
          <span>{t('form.loadingInfo')}</span>
        </div>
      )}

      {bookInfo && bookInfo.subjects.length > 0 && (
        <div className="subject-picker">
          <p className="subject-picker-label">
            {t('form.subjectQuestion')} <strong>{bookInfo.title}</strong>?
            <span className="subject-picker-hint"> {t('form.subjectHint')}</span>
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
              {t('form.subjectCount', { count: selectedSubjects.length })}
            </p>
          )}
        </div>
      )}

      {infoError && <p className="field-error">{infoError}</p>}

      <hr className="form-divider" />

      <div className="focus-slider-section">
        <span className="focus-slider-label">{t('form.sliderLabel')}</span>
        <FocusSlider value={styleWeight} onChange={setStyleWeight} />
      </div>

      <button type="submit" className="submit-btn" disabled={!isValid || loading}>
        {loading ? t('form.searching') : t('form.submit')}
        {!loading && <span className="submit-chevron">›</span>}
      </button>
    </form>
  )
}
