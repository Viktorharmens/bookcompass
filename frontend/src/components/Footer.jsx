import { useState } from 'react'

const MODALS = {
  howItWorks: {
    title: 'Hoe werkt BookCompass?',
    content: (
      <>
        <p>BookCompass helpt je boeken te ontdekken die lijken op een boek dat je al kent en waardeert — niet op basis van populariteit of genre-labels, maar op basis van hoe een boek <em>voelt</em>.</p>
        <h3>Wat je invoert</h3>
        <p>Je plakt een Open Library URL van een boek dat je aangeeft als vertrekpunt. BookCompass haalt automatisch de metadata op: titel, auteur, jaar en onderwerpen.</p>
        <h3>Wat er achter de schermen gebeurt</h3>
        <p>Elk boek in onze database is geanalyseerd op schrijfstijl en thematiek. Bij je zoekopdracht vergelijken we jouw boek met duizenden andere titels en berekenen we een overeenkomst. Je kunt zelf instellen hoeveel gewicht je geeft aan schrijfstijl versus thema.</p>
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

export default function Footer() {
  const [activeModal, setActiveModal] = useState(null)
  const modal = activeModal ? MODALS[activeModal] : null

  return (
    <>
      <footer className="app-footer">
        <span className="footer-copyright">© {new Date().getFullYear()} BookCompass</span>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('howItWorks')}>Hoe werkt het?</button>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('disclaimer')}>Disclaimer</button>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('privacy')}>Privacybeleid</button>
      </footer>

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
