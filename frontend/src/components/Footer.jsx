import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'

function getModals(t) {
  return {
    howItWorks: {
      title: t('modals.howItWorks.title'),
      content: (
        <>
          <p>{t('modals.howItWorks.intro')}</p>
          <h3>{t('modals.howItWorks.inputHeading')}</h3>
          <p>{t('modals.howItWorks.inputText')}</p>
          <h3>{t('modals.howItWorks.behindScenesHeading')}</h3>
          <p>{t('modals.howItWorks.behindScenesText')}</p>
          <h3>{t('modals.howItWorks.recommendationsHeading')}</h3>
          <p>{t('modals.howItWorks.recommendationsText')}</p>
        </>
      ),
    },
    disclaimer: {
      title: t('modals.disclaimer.title'),
      content: (
        <>
          <p>{t('modals.disclaimer.p1')}</p>
          <p>
            {t('modals.disclaimer.p2Start')}
            <a href="https://openlibrary.org" target="_blank" rel="noopener noreferrer">
              {t('modals.disclaimer.p2Link')}
            </a>
            {t('modals.disclaimer.p2End')}
          </p>
          <p>{t('modals.disclaimer.p3')}</p>
        </>
      ),
    },
    privacy: {
      title: t('modals.privacy.title'),
      content: (
        <>
          <p>{t('modals.privacy.p1')}</p>
          <h3>{t('modals.privacy.verwerkenHeading')}</h3>
          <p>{t('modals.privacy.verwerkenText')}</p>
          <h3>{t('modals.privacy.cookiesHeading')}</h3>
          <p>{t('modals.privacy.cookiesText')}</p>
          <h3>{t('modals.privacy.externalHeading')}</h3>
          <p>
            {t('modals.privacy.externalTextStart')}
            <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">
              {t('modals.privacy.externalTextLink')}
            </a>
            {t('modals.privacy.externalTextEnd')}
          </p>
        </>
      ),
    },
  }
}

function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const lang = i18n.language

  function toggle(lng) {
    i18n.changeLanguage(lng)
    localStorage.setItem('lang', lng)
    document.documentElement.lang = lng
  }

  return (
    <div className="lang-switcher">
      <button
        className={`lang-btn${lang === 'nl' ? ' active' : ''}`}
        onClick={() => toggle('nl')}
        aria-label="Nederlands"
      >NL</button>
      <span className="lang-sep">|</span>
      <button
        className={`lang-btn${lang === 'en' ? ' active' : ''}`}
        onClick={() => toggle('en')}
        aria-label="English"
      >EN</button>
    </div>
  )
}

function InfoSheet({ onClose }) {
  const { t } = useTranslation()
  const sheetRef = useRef(null)
  const startY = useRef(null)
  const currentDelta = useRef(0)
  const [closing, setClosing] = useState(false)
  const [activeSubModal, setActiveSubModal] = useState(null)

  const MODALS = getModals(t)

  const dismiss = () => {
    if (closing) return
    setClosing(true)
    document.body.classList.remove('sheet-open')
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
            <h2>{t('sheet.howItWorksTitle')}</h2>
            <p>{t('sheet.p1')}</p>
            <p>{t('sheet.p2')}</p>
          </section>

          <div className="info-sheet-footer">
            <span className="info-sheet-copyright">{t('footer.copyright', { year: new Date().getFullYear() })}</span>
            <div className="info-sheet-links">
              <button className="info-sheet-privacy-btn" onClick={() => setActiveSubModal('disclaimer')}>{t('footer.disclaimer')}</button>
              <span className="footer-sep">·</span>
              <button className="info-sheet-privacy-btn" onClick={() => setActiveSubModal('privacy')}>{t('footer.privacy')}</button>
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
              aria-label={t('footer.closeLabel')}
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
  const { t } = useTranslation()
  const [activeModal, setActiveModal] = useState(null)
  const [sheetOpen, setSheetOpen] = useState(false)

  const MODALS = getModals(t)
  const modal = activeModal ? MODALS[activeModal] : null

  return (
    <>
      {/* Regular footer (hidden in standalone PWA via CSS) */}
      <footer className="app-footer">
        <span className="footer-copyright">{t('footer.copyright', { year: new Date().getFullYear() })}</span>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('howItWorks')}>{t('footer.howItWorks')}</button>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('disclaimer')}>{t('footer.disclaimer')}</button>
        <span className="footer-sep">·</span>
        <button className="footer-link" onClick={() => setActiveModal('privacy')}>{t('footer.privacy')}</button>
      </footer>

      {/* Language switcher — fixed top-right on desktop, next to info button on mobile */}
      <LanguageSwitcher />

      {/* Info button only visible in standalone PWA */}
      <button
        className="pwa-info-btn"
        onClick={() => {
          setSheetOpen(true)
          document.body.classList.add('sheet-open')
        }}
        aria-label="Info"
      >
        i
      </button>

      {sheetOpen && <InfoSheet onClose={() => {
        setSheetOpen(false)
        document.body.classList.remove('sheet-open')
      }} />}

      {modal && (
        <div className="modal-overlay" onClick={() => setActiveModal(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{modal.title}</h2>
              <button className="modal-close" onClick={() => setActiveModal(null)} aria-label={t('footer.closeLabel')}>
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
