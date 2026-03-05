import { useState, useEffect, useRef } from 'react'
import {
  getAvailDates,
  getPreviewSpectrum,
  getPreviewMovie,
  getDaySummary,
  getVisitorCount,
  postQuery,
  postStage,
  getEphemeris,
  downloadUrl,
} from './api'

const MOVIE_FPS = 10 // frames per second for step (1 frame = 1/10 s)

function formatDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function parseDate(s) {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export default function App() {
  const [availDates, setAvailDates] = useState([])
  const [selectedDate, setSelectedDate] = useState('')
  const [spectrumUrls, setSpectrumUrls] = useState([])
  const [movieUrl, setMovieUrl] = useState(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [queryStart, setQueryStart] = useState('')
  const [queryEnd, setQueryEnd] = useState('')
  const [queryCadence, setQueryCadence] = useState(60)
  const [queryDataType, setQueryDataType] = useState('lev1_mfs')
  const [queryWithAllDaySpectrum, setQueryWithAllDaySpectrum] = useState(false)
  const [queryResults, setQueryResults] = useState(null)
  const [queryLoading, setQueryLoading] = useState(false)
  const [stageEmail, setStageEmail] = useState('')
  const [stageLoading, setStageLoading] = useState(false)
  const [stageDone, setStageDone] = useState(null)
  const [stageTurnstileToken, setStageTurnstileToken] = useState('')
  const [stageTurnstileError, setStageTurnstileError] = useState('')
  const [ephemeris, setEphemeris] = useState(null)
  const [ephemerisOpen, setEphemerisOpen] = useState(false)
  const turnstileContainerRef = useRef(null)
  const turnstileWidgetIdRef = useRef(null)
  const videoRef = useRef(null)
  const [movieTotalFrames, setMovieTotalFrames] = useState(0)
  const [movieCurrentFrame, setMovieCurrentFrame] = useState(0)
  const [moviePlaying, setMoviePlaying] = useState(false)
  const [movieSpeed, setMovieSpeed] = useState(1)
  const [movieSeeking, setMovieSeeking] = useState(false)
  const [seekPercent, setSeekPercent] = useState(0)
  const [daySummary, setDaySummary] = useState(null)
  const [visitorCount, setVisitorCount] = useState(null)

  // Initialize Cloudflare Turnstile widget
  useEffect(() => {
    let cancelled = false
    function initWidget() {
      if (cancelled) return
      if (window.turnstile && turnstileContainerRef.current) {
        const id = window.turnstile.render(turnstileContainerRef.current, {
          sitekey: import.meta.env.VITE_TURNSTILE_SITE_KEY,
          callback: (token) => {
            setStageTurnstileToken(token)
            setStageTurnstileError('')
          },
        })
        turnstileWidgetIdRef.current = id
      } else {
        setTimeout(initWidget, 500)
      }
    }
    initWidget()
    return () => {
      cancelled = true
      if (window.turnstile && turnstileWidgetIdRef.current) {
        window.turnstile.remove(turnstileWidgetIdRef.current)
        turnstileWidgetIdRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    getAvailDates()
      .then(setAvailDates)
      .catch(() => setAvailDates([]))
  }, [])

  useEffect(() => {
    getVisitorCount()
      .then((data) => {
        if (typeof data.count === 'number') setVisitorCount(data.count)
      })
      .catch(() => setVisitorCount(null))
  }, [])

  useEffect(() => {
    if (!selectedDate) return
    setLoadingPreview(true)
    Promise.all([getPreviewSpectrum(selectedDate), getPreviewMovie(selectedDate)])
      .then(([spec, mov]) => {
        setSpectrumUrls(spec.urls || [])
        setMovieUrl(mov.url || null)
      })
      .catch(() => {
        setSpectrumUrls([])
        setMovieUrl(null)
      })
      .finally(() => setLoadingPreview(false))
  }, [selectedDate])

  useEffect(() => {
    const sorted = [...availDates].sort()
    if (sorted.length > 0) {
      setSelectedDate(sorted[sorted.length - 1])
    } else {
      const yesterday = new Date()
      yesterday.setDate(yesterday.getDate() - 1)
      setSelectedDate(formatDate(yesterday))
    }
  }, [availDates])

  // When preview date changes, set query range to that day in UTC (00:00:00 – 23:59:59)
  useEffect(() => {
    if (!selectedDate) return
    setQueryStart(`${selectedDate} 00:00:00`)
    setQueryEnd(`${selectedDate} 23:59:59`)
    // Load per-day product counts for badges
    getDaySummary(selectedDate)
      .then(setDaySummary)
      .catch(() => setDaySummary(null))
  }, [selectedDate])

  function changeDay(offset) {
    if (!selectedDate) return
    const d = parseDate(selectedDate)
    d.setDate(d.getDate() + offset)
    setSelectedDate(formatDate(d))
  }

  // Parse "YYYY-MM-DD HH:MM:SS" as UTC for validation
  function parseUtcTime(s) {
    if (!s || typeof s !== 'string') return null
    const normalized = s.trim().replace('T', ' ').slice(0, 19)
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(normalized)) {
      return new Date(normalized + 'Z').getTime()
    }
    return NaN
  }
  const queryStartMs = parseUtcTime(queryStart)
  const queryEndMs = parseUtcTime(queryEnd)
  const durationNegative = queryStartMs != null && queryEndMs != null && queryStartMs >= queryEndMs
  const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000
  const durationTooLong = queryStartMs != null && queryEndMs != null && (queryEndMs - queryStartMs) > SEVEN_DAYS_MS
  const queryDisabled = queryLoading || durationNegative || durationTooLong || !queryStart?.trim() || !queryEnd?.trim() || Number.isNaN(queryStartMs) || Number.isNaN(queryEndMs)
  const queryDisabledTooltip = durationNegative ? 'duration < 0' : durationTooLong ? 'time too long' : ''

  function handleQuery(e) {
    e.preventDefault()
    if (!queryStart || !queryEnd || queryDisabled) return
    setQueryLoading(true)
    setStageDone(null)
    postQuery({
      start_time: queryStart.trim().replace('T', ' ').slice(0, 19),
      end_time: queryEnd.trim().replace('T', ' ').slice(0, 19),
      data_type: queryDataType,
      cadence: queryCadence || null,
      with_all_day_spectrum: queryWithAllDaySpectrum,
    })
      .then((res) => {
        if (res.file_count > 400) {
          window.alert('Too many files in one request')
        }
        setQueryResults(res)
      })
      .catch((err) => setQueryResults({ error: err.message, file_count: 0, total_size_bytes: 0, stage_available: false }))
      .finally(() => setQueryLoading(false))
  }

  function formatBytes(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(2) + ' GB'
    if (n >= 1e6) return (n / 1e6).toFixed(2) + ' MB'
    if (n >= 1e3) return (n / 1e3).toFixed(2) + ' KB'
    return n + ' B'
  }

  function handleStage(e) {
    e.preventDefault()
    if (!stageEmail.trim() || !queryResults?.stage_available) return
    if (!stageTurnstileToken) {
      setStageTurnstileError('Please complete the verification.')
      return
    }
    setStageLoading(true)
    setStageTurnstileError('')
    postStage({
      start_time: queryResults.start_time,
      end_time: queryResults.end_time,
      data_type: queryDataType,
      cadence: queryCadence || null,
      with_all_day_spectrum: queryWithAllDaySpectrum,
      email: stageEmail.trim(),
      turnstile_token: stageTurnstileToken,
    })
      .then(setStageDone)
      .catch((err) => { setStageDone({ error: err.message }) })
      .finally(() => setStageLoading(false))
  }

  function loadEphemeris() {
    if (ephemeris) return
    getEphemeris().then(setEphemeris).catch(() => setEphemeris({ error: 'Failed to load' }))
  }

  const dailySpec = spectrumUrls.length > 0 ? spectrumUrls[0] : null
  const hourlySpecs = spectrumUrls.slice(1)
  const sortedAvail = [...availDates].sort()

  function movieStepFrames(delta) {
    const v = videoRef.current
    if (!v || !isFinite(v.duration)) return
    const frameTime = 1 / MOVIE_FPS
    let t = v.currentTime + delta * frameTime
    t = Math.max(0, Math.min(v.duration, t))
    v.currentTime = t
    setMovieCurrentFrame(Math.round(t * MOVIE_FPS))
  }

  function moviePlayPause() {
    const v = videoRef.current
    if (!v) return
    if (v.paused) {
      v.playbackRate = movieSpeed
      v.play()
      setMoviePlaying(true)
    } else {
      v.pause()
      setMoviePlaying(false)
    }
  }

  function movieSetSpeed(val) {
    const s = Math.max(0.25, Math.min(4, Number(val) || 1))
    setMovieSpeed(s)
    const v = videoRef.current
    if (v && !v.paused) v.playbackRate = s
  }
  const minDate = sortedAvail.length > 0 ? sortedAvail[0] : undefined
  const maxDate = sortedAvail.length > 0 ? sortedAvail[sortedAvail.length - 1] : undefined

  return (
    <div className="min-h-screen p-4 md:p-6 max-w-7xl mx-auto">
      <header className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <h1 className="text-2xl md:text-3xl font-bold text-white">
          OVRO LWA Solar Data Portal
        </h1>
        <div className="text-xs text-slate-400 sm:text-right">
          <span
            role="img"
            aria-label="wave"
            className="mr-1"
          >
            👋
          </span>
          {visitorCount !== null
            ? `Welcome as ${visitorCount.toLocaleString()} visitor`
            : 'Welcome'}
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Left block: date selection + spectrum preview */}
        <div className="flex flex-col gap-4">
          <div className="rounded border border-gray-600 bg-gray-800/50 p-3">
            <label className="block text-sm text-gray-300 mb-1">Date (UTC)</label>
            <div className="flex flex-wrap items-end gap-2">
              <div className="relative inline-flex items-center">
                <input
                  type="date"
                  className="date-input-emoji bg-gray-800 text-white rounded px-3 py-2 border border-gray-600 pr-8"
                  value={selectedDate}
                  min={minDate}
                  max={maxDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                />
                <span className="pointer-events-none absolute right-2 text-lg" aria-hidden>📅</span>
              </div>
              <button
                type="button"
                className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded"
                onClick={() => changeDay(-1)}
              >
                -1 Day
              </button>
              <button
                type="button"
                className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded"
                onClick={() => changeDay(1)}
              >
                +1 Day
              </button>
            </div>
            {minDate && maxDate && (
              <p className="text-xs text-gray-500 mt-1">Data available from {minDate} to {maxDate}</p>
            )}
          </div>

          <div>
            <h2 className="text-xl font-semibold text-white mb-2">Preview</h2>
            {loadingPreview && <p className="text-gray-400">Loading…</p>}
            {!loadingPreview && !dailySpec && !movieUrl && spectrumUrls.length === 0 && selectedDate && (
              <p className="text-gray-400">No data for this day.</p>
            )}
            <h3 className="text-lg text-gray-200 mb-2">Daily spectrogram</h3>
            {dailySpec && (
              <div>
                <img
                  src={dailySpec}
                  alt="Daily spectrum"
                  className="max-w-full rounded border border-gray-600"
                />
              </div>
            )}
            {daySummary && (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-300">
                <span className="text-gray-400">Data available:</span>
                {daySummary.n_spec_daily_fits > 0 && (
                  <span className="inline-flex items-center rounded-full bg-gray-700 px-2 py-0.5 text-gray-100">
                    <span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-400" />
                    {daySummary.n_spec_daily_fits} spec fits
                  </span>
                )}
                {daySummary.n_img_lev1_mfs > 0 && (
                  <span className="inline-flex items-center rounded-full bg-gray-700 px-2 py-0.5 text-gray-100">
                    <span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-400" />
                    {daySummary.n_img_lev1_mfs} lev1 mfs hdf
                  </span>
                )}
                {daySummary.n_img_lev1_fch > 0 && (
                  <span className="inline-flex items-center rounded-full bg-gray-700 px-2 py-0.5 text-gray-100">
                    <span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-400" />
                    {daySummary.n_img_lev1_fch} lev1 fch hdf
                  </span>
                )}
                {daySummary.n_img_lev15_mfs > 0 && (
                  <span className="inline-flex items-center rounded-full bg-gray-700 px-2 py-0.5 text-gray-100">
                    <span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-400" />
                    {daySummary.n_img_lev15_mfs} lev15 mfs hdf
                  </span>
                )}
                {daySummary.n_img_lev15_fch > 0 && (
                  <span className="inline-flex items-center rounded-full bg-gray-700 px-2 py-0.5 text-gray-100">
                    <span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-400" />
                    {daySummary.n_img_lev15_fch} lev15 fch hdf
                  </span>
                )}
              </div>
            )}
            {!dailySpec && selectedDate && !loadingPreview && <p className="text-gray-500">No daily spectrum.</p>}
          </div>
        </div>

        {/* Right block: daily movie */}
        <div>
            <h3 className="text-lg text-gray-200 mb-2">Daily movie</h3>
            {movieUrl && (
              <>
                <video
                  ref={videoRef}
                  key={selectedDate}
                  src={movieUrl}
                  className="w-full rounded border border-gray-600 bg-black"
                  onLoadedMetadata={(e) => {
                    const v = e.target
                    const dur = v.duration
                    if (isFinite(dur)) {
                      setMovieTotalFrames(Math.round(dur * MOVIE_FPS))
                      setMovieCurrentFrame(0)
                    } else {
                      setMovieTotalFrames(0)
                      setMovieCurrentFrame(0)
                    }
                    setSeekPercent(0)
                    setMoviePlaying(false)
                  }}
                  onTimeUpdate={(e) => {
                    const v = e.target
                    if (isFinite(v.duration)) {
                      setMovieCurrentFrame(Math.round(v.currentTime * MOVIE_FPS))
                      if (!movieSeeking) setSeekPercent((v.currentTime / v.duration) * 100)
                    }
                  }}
                  onPlay={() => setMoviePlaying(true)}
                  onPause={() => setMoviePlaying(false)}
                  onEnded={() => setMoviePlaying(false)}
                />
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={0.1}
                  value={seekPercent}
                  className="mt-1.5 h-2 w-full cursor-pointer appearance-none rounded-lg bg-gray-700 accent-gray-500"
                  onMouseDown={() => setMovieSeeking(true)}
                  onMouseUp={() => setMovieSeeking(false)}
                  onTouchStart={() => setMovieSeeking(true)}
                  onTouchEnd={() => setMovieSeeking(false)}
                  onChange={(e) => {
                    const p = Number(e.target.value)
                    setSeekPercent(p)
                    const v = videoRef.current
                    if (v && isFinite(v.duration)) {
                      v.currentTime = (p / 100) * v.duration
                      setMovieCurrentFrame(Math.round(v.currentTime * MOVIE_FPS))
                    }
                  }}
                />
                <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 rounded border border-gray-600 bg-gray-800/80 px-2 py-1.5 text-sm text-gray-200">
                  <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="rounded bg-gray-600 px-2 py-0.5 hover:bg-gray-500"
                    onClick={moviePlayPause}
                  >
                    {moviePlaying ? 'Stop' : 'Play'}
                  </button>
                  <label className="flex items-center gap-1">
                    speed
                    <input
                      type="number"
                      min="0.25"
                      max="4"
                      step="0.25"
                      className="w-14 rounded border border-gray-600 bg-gray-900 px-1 py-0.5 text-right"
                      value={movieSpeed}
                      onChange={(e) => movieSetSpeed(e.target.value)}
                    />
                    x1
                  </label>
                  <button
                    type="button"
                    className="rounded bg-gray-600 px-2 py-0.5 hover:bg-gray-500"
                    onClick={() => movieStepFrames(-10)}
                    title="Previous 10 frames"
                  >
                    &lt;&lt;
                  </button>
                  <button
                    type="button"
                    className="rounded bg-gray-600 px-2 py-0.5 hover:bg-gray-500"
                    onClick={() => movieStepFrames(-1)}
                    title="Previous frame"
                  >
                    &lt;
                  </button>
                  <button
                    type="button"
                    className="rounded bg-gray-600 px-2 py-0.5 hover:bg-gray-500"
                    onClick={() => movieStepFrames(1)}
                    title="Next frame"
                  >
                    &gt;
                  </button>
                  <button
                    type="button"
                    className="rounded bg-gray-600 px-2 py-0.5 hover:bg-gray-500"
                    onClick={() => movieStepFrames(10)}
                    title="Next 10 frames"
                  >
                    &gt;&gt;
                  </button>
                  </div>
                  <div className="flex items-center gap-3">
                    <span>Total <span className="font-mono">[{movieTotalFrames}]</span></span>
                    <span>Current <span className="font-mono">[{movieCurrentFrame}]</span></span>
                  </div>
                </div>
              </>
            )}
            {!movieUrl && selectedDate && !loadingPreview && <p className="text-gray-500">No movie for this date.</p>}
        </div>
      </div>

      {hourlySpecs.length > 0 && (
        <section className="mb-8">
          <h3 className="text-lg text-gray-200 mb-2">Hourly spectrograms</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            {hourlySpecs.map((url, i) => (
              <a
                key={i}
                href={url}
                target="_blank"
                rel="noreferrer"
                className="block"
              >
                <img
                  src={url}
                  alt={`Hourly ${i + 1}`}
                  className="w-full rounded border border-gray-600 hover:border-blue-500"
                />
              </a>
            ))}
          </div>
        </section>
      )}

      <section className="mb-8 max-w-2xl">
        <div className="rounded border border-gray-600 bg-gray-800/50 p-4">
          <h2 className="text-xl font-semibold text-white mb-2">Data query</h2>
          <p className="text-sm text-gray-400 mb-3">All times in UTC, 24-hour format.</p>
          <form onSubmit={handleQuery} className="flex flex-col gap-4 mb-3">
            <div>
              <label className="block text-sm text-gray-300 mb-1">Start time (UTC, 24h)</label>
              <input
                type="text"
                className="bg-gray-800 text-white rounded px-3 py-2 border border-gray-600 w-full max-w-xs font-mono"
                placeholder="YYYY-MM-DD HH:MM:SS"
                value={queryStart}
                onChange={(e) => setQueryStart(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">End time (UTC, 24h)</label>
              <input
                type="text"
                className="bg-gray-800 text-white rounded px-3 py-2 border border-gray-600 w-full max-w-xs font-mono"
                placeholder="YYYY-MM-DD HH:MM:SS"
                value={queryEnd}
                onChange={(e) => setQueryEnd(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Cadence (s)</label>
              <input
                type="number"
                min="1"
                className="bg-gray-800 text-white rounded px-3 py-2 border border-gray-600 w-20"
                value={queryCadence}
                onChange={(e) => setQueryCadence(Number(e.target.value) || 60)}
              />
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Data type</label>
              <select
                className="bg-gray-800 text-white rounded px-3 py-2 border border-gray-600"
                value={queryDataType}
                onChange={(e) => setQueryDataType(e.target.value)}
              >
                <option value="lev1_mfs">lev1 mfs</option>
                <option value="lev1_fch">lev1 fch</option>
                <option value="lev15_mfs">lev15 mfs</option>
                <option value="lev15_fch">lev15 fch</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="with-all-day-spectrum"
                className="rounded border-gray-600 bg-gray-800"
                checked={queryWithAllDaySpectrum}
                onChange={(e) => setQueryWithAllDaySpectrum(e.target.checked)}
              />
              <label htmlFor="with-all-day-spectrum" className="text-sm text-gray-300">With all day spectrum</label>
            </div>
            <button
              type="submit"
              className="inline-flex items-center self-start bg-green-600 hover:bg-green-700 text-white text-sm px-4 py-2 rounded disabled:opacity-50"
              disabled={queryDisabled}
              title={queryDisabledTooltip}
            >
              {queryLoading ? 'Querying…' : 'Query'}
            </button>
          </form>
          {queryResults && (
            <>
              {queryResults.error && <p className="text-red-400 mb-2">{queryResults.error}</p>}
              {!queryResults.error && (
                <p className="text-gray-300 mb-1">
                  {queryResults.file_count ?? 0} file(s), total {formatBytes(queryResults.total_size_bytes ?? 0)}
                </p>
              )}
            </>
          )}
        </div>

        {queryResults?.stage_available && (
          <div className="mt-4 rounded border border-gray-600 bg-gray-800/50 p-4">
            <h3 className="text-lg text-gray-200 mb-3">Stage</h3>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-1 text-sm text-gray-300 mb-3">
              <dt>Start time (UTC):</dt>
              <dd className="font-mono">{queryResults.start_time}</dd>
              <dt>End time (UTC):</dt>
              <dd className="font-mono">{queryResults.end_time}</dd>
              <dt>Number of files:</dt>
              <dd>{queryResults.file_count}</dd>
              <dt>Total size:</dt>
              <dd>{formatBytes(queryResults.total_size_bytes)}</dd>
            </dl>
            <p className="text-sm text-gray-400 mb-3">
              The data is available for staging. After staging is ready, we will email you the download link from ovsa.operations.noreply@gmail.com — please check your spam.
            </p>
            {!stageDone ? (
              <form onSubmit={handleStage} className="flex flex-col gap-3">
                <div className="flex flex-wrap items-end gap-2">
                  <label className="sr-only" htmlFor="stage-email">Email</label>
                  <input
                    id="stage-email"
                    type="email"
                    placeholder="your@email.com"
                    className="bg-gray-800 text-white rounded px-3 py-2 border border-gray-600 w-56"
                    value={stageEmail}
                    onChange={(e) => setStageEmail(e.target.value)}
                  />
                  <button
                    type="submit"
                    className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded disabled:opacity-50"
                    disabled={!stageEmail.trim() || stageLoading}
                  >
                    {stageLoading ? 'Staging…' : 'Stage'}
                  </button>
                </div>
                <div
                  ref={turnstileContainerRef}
                  className="cf-turnstile"
                />
                {stageTurnstileError && (
                  <p className="text-sm text-red-400">{stageTurnstileError}</p>
                )}
              </form>
            ) : stageDone.error ? (
              <p className="text-red-400">{stageDone.error}</p>
            ) : (
              <p className="text-gray-300">
                Ready. <a href={stageDone.download_url} className="text-blue-400 hover:underline" target="_blank" rel="noreferrer">Download zip</a> at {stageDone.download_url}
              </p>
            )}
          </div>
        )}
      </section>

      <section>
        <button
          type="button"
          className="text-gray-300 hover:text-white mb-2"
          onClick={() => { setEphemerisOpen(!ephemerisOpen); loadEphemeris(); }}
        >
          {ephemerisOpen ? '▼' : '▶'} OVRO Sun Ephemeris
        </button>
        {ephemerisOpen && (
          <div className="bg-gray-800/50 rounded p-4 border border-gray-600 text-sm">
            {!ephemeris && <p className="text-gray-400">Loading…</p>}
            {ephemeris?.error && <p className="text-red-400">{ephemeris.error}</p>}
            {ephemeris && !ephemeris.error && (
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <dt className="text-gray-400">Current UTC</dt>
                <dd>{ephemeris.current_time_utc}</dd>
                <dt className="text-gray-400">Sun (alt / az)</dt>
                <dd>{ephemeris.alt_deg}° / {ephemeris.az_deg}°</dd>
                <dt className="text-gray-400">Sunrise 0° (UTC)</dt>
                <dd>{ephemeris.sunrise_utc}</dd>
                <dt className="text-gray-400">Sunset 0° (UTC)</dt>
                <dd>{ephemeris.sunset_utc}</dd>
                <dt className="text-gray-400">Sun above 12° (UTC)</dt>
                <dd>{ephemeris.sun_12up_utc ?? 'N/A'}</dd>
                <dt className="text-gray-400">Sun below 12° (UTC)</dt>
                <dd>{ephemeris.sun_12down_utc ?? 'N/A'}</dd>
              </dl>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
