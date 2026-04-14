import { useState } from 'react'
import { useTranslation } from 'react-i18next'

const AMAZON_TAG  = import.meta.env.VITE_AMAZON_TAG    || ""
const BOL_PARTNER = import.meta.env.VITE_BOL_PARTNER_ID || ""

function buyLinks(title, author) {
  const q       = encodeURIComponent(`${title} ${author}`.trim())
  const amazon  = AMAZON_TAG
    ? `https://www.amazon.com/s?k=${q}&tag=${AMAZON_TAG}`
    : `https://www.amazon.com/s?k=${q}`
  const bol     = BOL_PARTNER
    ? `https://www.bol.com/nl/nl/s/?searchtext=${q}&partnerid=${BOL_PARTNER}`
    : `https://www.bol.com/nl/nl/s/?searchtext=${q}`
  return { amazon, bol }
}

function BookCard({ book, rank }) {
  const { t } = useTranslation()
  const [descOpen, setDescOpen] = useState(false)
  const olUrl           = `https://openlibrary.org${book.ol_key}`
  const pct             = Math.round(book.score * 100)
  const { amazon, bol } = buyLinks(book.title, book.author)

  return (
    <article className="book-card">
      <div className="book-card-top">
        <div className="book-cover">
          {book.cover_url
            ? <img src={book.cover_url} alt={book.title} />
            : <div className="cover-placeholder">{book.title.charAt(0)}</div>
          }
        </div>
        <div className="book-info">
          <div className="book-title-row">
            <h3 className="book-title">
              <a href={olUrl} target="_blank" rel="noopener noreferrer">{book.title}</a>
            </h3>
            <span className="book-score-pct">{pct}%</span>
          </div>
          <p className="book-author">
            {book.author}{book.year ? <span className="book-year"> · {book.year}</span> : null}
          </p>
        </div>
      </div>

      <div className="card-divider" />

      {book.subjects.length > 0 && (
        <div className="tag-row">
          {book.subjects.slice(0, 4).map(s => (
            <span key={s} className="tag">{s}</span>
          ))}
        </div>
      )}

      {book.description && (
        <div className="book-desc">
          <button className="desc-toggle" onClick={() => setDescOpen(o => !o)}>
            <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M4 6h12M4 10h8M4 14h10" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/>
            </svg>
            {t('results.description')}
            <svg className={`toggle-chevron${descOpen ? ' open' : ''}`} viewBox="0 0 20 20" fill="none">
              <path d="M5 8l5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
          {descOpen && <p className="desc-text">{book.description}</p>}
        </div>
      )}

      <div className="book-why">
        <p className="why-label">{t('results.whyThisBook')}</p>
        <p className="why-text">{book.explanation}</p>
      </div>

      <div className="buy-row">
        <a className="buy-btn buy-bol"    href={bol}    target="_blank" rel="noopener noreferrer sponsored">{t('results.buyBol')}</a>
        <a className="buy-btn buy-amazon" href={amazon} target="_blank" rel="noopener noreferrer sponsored">{t('results.buyAmazon')}</a>
      </div>
    </article>
  )
}

export default function ResultsList({ books, queryBook }) {
  const { t } = useTranslation()
  if (!books?.length) return <p className="no-results">{t('results.noResults')}</p>

  return (
    <>
      {queryBook && (
        <div className="query-chip">
          <div className="query-chip-left">
            {queryBook.cover_url
              ? <img src={queryBook.cover_url} alt={queryBook.title} className="query-chip-cover" />
              : <div className="query-chip-placeholder">📖</div>
            }
            <div className="query-chip-text">
              <p className="query-chip-label">{t('results.basedOn')}</p>
              <p className="query-chip-title">{queryBook.title}</p>
              <p className="query-chip-author">{queryBook.author}</p>
            </div>
          </div>
          <span className="query-chip-badge">{books.length} {t('results.recommendations')}</span>
        </div>
      )}

      <div className="results-list">
        {books.map((book, i) => <BookCard key={book.ol_key + i} book={book} rank={i + 1} />)}
      </div>
    </>
  )
}
