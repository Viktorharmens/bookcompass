import { useState, useRef } from 'react'

const MODALS = {
  howItWorks: {
    title: 'Hoe werkt BookCompass?',
    content: (
      <>
        <p>BookCompass helpt je boeken te ontdekken die lijken op een boek dat je al kent en waardeert — niet op basis van populariteit of genre-labels, maar op basis van hoe een boek <em>voelt</em>.</p>
        <h3>Wat je invoert</h3>
        <p>Je voert een boektitel, ISBN, of URL in van bol.com, Amazon, Goodreads of Open Library. BookCompass haalt automatisch de metadata op: titel, auteur, jaar en onderwerpen.</p>
        <h3>Wat er achter de schermen gebeurt</h3>
        <p>Een AI-model analyseert jouw boek en zoekt naar de beste overeenkomsten op basis van thematiek en schrijfstijl. Je kunt zelf instellen hoeveel gewicht je geeft aan schrijfstijl versus thema.</p>
        <h3>De aanbevelingen</h3>
        <p>Je krijgt een lijst van boeken gerangschikt op overeenkomst, elk met een korte uitleg waarom dit boek bij jou past. Via de knoppen kun je ze direct opzoeken bij bol.com of Amazon.</p>
      </>
    ),
  },
  disclaimer: {
    title: 'Disclaimer',
    content: (
      <>
        <p>BookCompass is een persoonlijk project en wordt aangeboden zoals het is, zonder enige garantie op volledigheid of nauwkeurigheid van de aanbevelingen.</p>
        <p>De informatie over boeken (titels, auteurs, covers) is afkomstig van <a href="https://openlibrary.org" target="_blank" rel="noopener noreferrer">Open Library</a>, een open databron. BookCompass heeft geen commerciële binding met Open Library, bol.com of Amazon.</p>
        <p>Links naar externe winkels zijn gemakshalve toegevoegd. BookCompass ontvangt geen vergoeding voor doorklikken of aankopen.</p>
      </>
    ),
  },
  privacy: {
    title: 'Privacybeleid',
    content: (
      <>
        <p>BookCompass verzamelt geen persoonlijke gegevens. Er is geen account, geen login en geen tracking.</p>
        <h3>Wat we verwerken</h3>
        <p>De Open Library URL die je invoert wordt alleen gebruikt om je zoekopdracht uit te voeren en wordt niet opgeslagen na het verwerken van je verzoek.</p>
        <h3>Cookies</h3>
        <p>BookCompass gebruikt geen cookies of andere trackingmethoden.</p>
        <h3>Externe diensten</h3>
        <p>De pagina laadt lettertypen via Google Fonts. Hierbij wordt je IP-adres gedeeld met Google. Raadpleeg het <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">privacybeleid van Google</a> voor meer informatie.</p>
      </>
    ),
  },
}

function InfoSheet({ onClose }) {
  const sheetRef = useRef(null)
  const startY = useRef(null)
  const currentDelta = useRef(0)
  const [closing, setClosing] = useState(false)
  const [activeSubModal, setActiveSubModal] = useState(null)

  const dismiss = () => {
    if (closing) return
    setClosing(true)
    setTimeout(onClose, 280)
  }

  const onTouchStart = (e) => {
    startY.current = e.touches[0].clientY
    currentDelta.current = 0
    if (sheetRef.current) sheetRef.current.style.transition = 'none'
  }

  const onTouchMove = (e) => {
    if (startY.current === null) return
    const dy = e.touches[0].clientY - startY.current
    if (dy <= 0) return
    currentDelta.current = dy
    if (sheetRef.current) sheetRef.current.style.transform = `translateY(${dy}px)`
  }

  const onTouchEnd = () => {
    if (sheetRef.current) {
      sheetRef.current.style.transition = 'transform 0.28s cubic-bezier(0.32, 0.72, 0, 1)'
    }
    if (currentDelta.current > 100) {
      dismiss()
    } else {
      if (sheetRef.current) sheetRef.current.style.transform = 'translateY(0)'
    }
    startY.current = null
    currentDelta.current = 0
  }

  return (
    <div
      className={`info-sheet-overlay${closing ? ' closing' : ''}`}
      onClick={dismiss}
    >
      <div
        className={`info-sheet${closing ? ' closing' : ''}`}
        ref={sheetRef}
        onClick={e => e.stopPropagation()}
      >
        <div
          className="info-sheet-handle-area"
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
        >
          <div className="info-sheet-handle" />
        </div>

        <div className="info-sheet-body">
          <section className="info-section">
            <h2>Hoe werkt BookCompass?</h2>
            <p>Voer een boektitel, ISBN of URL in van bol.com, Amazon, Goodreads of Open Library. BookCompass haalt de metadata op en gebruikt AI om boeken te vinden die qua thematiek en schrijfstijl het best bij jou passen — niet op basis van populariteit, maar op gevoel.</p>
            <p>Met de schuifregelaar stel je zelf in hoeveel gewicht je geeft aan schrijfstijl versus thema. Je krijgt een gerangschikte lijst met een korte uitleg per aanbeveling.</p>
          </section>

          <div className="info-sheet-footer">
            <span className="info-sheet-copyright">© {new Date().getFullYear()} BookCompass</span>
            <div className="info-sheet-links">
              <button className="info-sheet-privacy-btn" onClick={() => setActiveSubModal('disclaimer')}>Disclaimer</button>
              <span className="footer-sep">·</span>
              <button className="info-sheet-privacy-btn" onClick={() => setActiveSubModal('privacy')}>Privacybeleid</button>
            </div>
          </div>
        </div>
      </div>

      {activeSubModal && (
        <div className="info-sub-modal" onClick={e => e.stopPropagation()}>
          <div className="info-sub-modal-header">
            <h2>{MODALS[activeSubModal].title}</h2>
            <button
              className="modal-close"
              onClick={() => setActiveSubModal(null)}
              aria-label="Sluiten"
            >
              <svg viewBox="0 0 20 20" fill="none">
                <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </button>
          </div>
          <div className="modal-body">
            {MODALS[activeSubModal].content}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Footer() {
  const [activeModal, setActiveModal] = useState(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const modal = activeModal ? MODALS[activeModal] : null

  return (
    <>
      {/* Reguliere footer (verborgen in standalone PWA via CSS) */}
      <footer className="app-footer">
        <span className="footer-copyright">© {new Date().getFullYear()} BookCompass</span>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('howItWorks')}>Hoe werkt het?</button>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('disclaimer')}>Disclaimer</button>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('privacy')}>Privacybeleid</button>
      </footer>

      {/* Info-knop alleen zichtbaar in standalone PWA */}
      <button
        className="pwa-info-btn"
        onClick={() => setSheetOpen(true)}
        aria-label="Info"
      >
        i
      </button>

      {sheetOpen && <InfoSheet onClose={() => setSheetOpen(false)} />}

      {modal && (
        <div className="modal-overlay" onClick={() => setActiveModal(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{modal.title}</h2>
              <button className="modal-close" onClick={() => setActiveModal(null)} aria-label="Sluiten">
                <svg viewBox="0 0 20 20" fill="none">
                  <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                </svg>
              </button>
            </div>
            <div className="modal-body">{modal.content}</div>
          </div>
        </div>
      )}
    </>
  )
}
