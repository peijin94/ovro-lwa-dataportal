import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// Global callback for Cloudflare Turnstile; App will attach a handler.
// eslint-disable-next-line no-underscore-dangle
window.__lwaSetTurnstileToken = null
// eslint-disable-next-line no-underscore-dangle
window.__lwaTurnstileCallback = (token) => {
  if (typeof window.__lwaSetTurnstileToken === 'function') {
    window.__lwaSetTurnstileToken(token)
  }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
