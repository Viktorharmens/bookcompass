const AMAZON_TAG    = import.meta.env.VITE_AMAZON_TAG    || ""
const BOL_PARTNER   = import.meta.env.VITE_BOL_PARTNER_ID || ""

function buyLinks(title, author) {
  const q = encodeURIComponent(`${title} ${author}`.trim())
  const amazon = AMAZON_TAG
    ? `https://www.amazon.com/s?k=${q}&tag=${AMAZON_TAG}`
    : `https://www.amazon.com/s?k=${q}`
  const bol = BOL_PARTNER
    ? `https://www.bol.com/nl/nl/s/?searchtext=${q}&utm_source=boekfinder&utm_medium=affiliate&partnerid=${BOL_PARTNER}`
    : `https://www.bol.com/nl/nl/s/?searchtext=${q}`
  return { amazon, bol }
}

function BookCard({ book, rank }) {
  const olUrl = `https://openlibrary.org${book.ol_key}`
  const pct   = Math.round(book.score * 100)
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
        <div className="book-meta">
          <span className="book-rank">#{rank} aanbeveling</span>
          <h3 className="book-title">
            <a href={olUrl} target="_blank" rel="noopener noreferrer">{book.title}</a>
          </h3>
          <p className="book-author">
            {book.author}{book.year ? <span className="book-year"> · {book.year}</span> : null}
          </p>
          <div className="score-row">
            <div className="score-track">
              <div className="score-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="score-pct">{pct}%</span>
          </div>
        </div>
      </div>

      <div className="book-why">
        <p className="why-label">Waarom dit boek?</p>
        <p className="why-text">{book.explanation}</p>
      </div>

      {book.subjects.length > 0 && (
        <div className="tag-row">
          {book.subjects.slice(0, 4).map(s => (
            <span key={s} className="tag">{s}</span>
          ))}
        </div>
      )}

      <div className="buy-row">
        <a className="buy-btn buy-bol"    href={bol}    target="_blank" rel="noopener noreferrer sponsored">Kopen bij bol.com</a>
        <a className="buy-btn buy-amazon" href={amazon} target="_blank" rel="noopener noreferrer sponsored">Amazon</a>
      </div>
    </article>
  )
}

export default function ResultsList({ books }) {
  if (!books?.length) return <p className="no-results">Geen resultaten gevonden.</p>

  return (
    <>
      <p className="results-header">{books.length} aanbevelingen</p>
      <div className="results-list">
        {books.map((book, i) => <BookCard key={book.ol_key + i} book={book} rank={i + 1} />)}
      </div>
    </>
  )
}
