/**
 * Portal API client.
 *
 * Base priority:
 * - VITE_API_BASE (explicit backend base URL, e.g. https://ovsa.njit.edu/lwa)
 * - import.meta.env.BASE_URL (Vite base, e.g. '/' in dev or '/lwa/' in prod)
 * - '' (same-origin root)
 */
const rawBase =
  typeof import.meta.env !== 'undefined' && typeof import.meta.env.VITE_API_BASE !== 'undefined'
    ? import.meta.env.VITE_API_BASE
    : (typeof import.meta.env !== 'undefined' && typeof import.meta.env.BASE_URL !== 'undefined'
        ? import.meta.env.BASE_URL
        : '')

// Normalize: remove trailing slash (except for ""), so "", "/lwa/", or
// "https://ovsa.njit.edu/lwa/" all become usable prefixes.
const BASE = (rawBase || '').replace(/\/$/, '')

function portal(path, options = {}) {
  const url = `${BASE}/portal${path.startsWith('/') ? path : `/${path}`}`
  return fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } })
    .then((r) => {
      if (!r.ok) throw new Error(r.statusText || r.status)
      return r.json()
    })
}

export function getAvailDates() {
  return portal('/avail-dates')
}

export function getPreviewSpectrum(date) {
  return portal(`/preview/spectrum/${date}`)
}

export function getPreviewMovie(date) {
  return portal(`/preview/movie/${date}`)
}

export function getDaySummary(date) {
  return portal(`/day-summary/${date}`)
}

export function getVisitorCount() {
  return portal('/visitors/count')
}

export function postQuery(body) {
  return fetch(`${BASE}/portal/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => {
    if (!r.ok) throw new Error(r.statusText || r.status)
    return r.json()
  })
}

export function postStage(body) {
  return fetch(`${BASE}/portal/stage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json().then((data) => {
    if (!r.ok) throw new Error(data.detail || r.statusText)
    return data
  }))
}

export function getEphemeris() {
  return portal('/ephemeris')
}

/**
 * URL for inline file (image/video). root and path from API response.
 */
export function fileUrl(root, path) {
  const params = new URLSearchParams({ root, path })
  return `${BASE}/portal/files?${params.toString()}`
}

/**
 * URL for download (attachment).
 */
export function downloadUrl(root, path) {
  const params = new URLSearchParams({ root, path })
  return `${BASE}/portal/download?${params.toString()}`
}
