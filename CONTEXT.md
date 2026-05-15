# OVRO LWA Solar Data Portal

This context describes the user-facing solar data products shown in the OVRO LWA data portal and the language used when coordinating previews across products.

## Language

**Daily spectrogram**:
An all-day radio spectrum preview image for a selected UTC date.
_Avoid_: Daily spectrum, spectrum preview

**Daily movie**:
A daily synoptic MFS image movie for a selected UTC date.
_Avoid_: Movie preview, video

**Movie frame time**:
The UTC observation timestamp represented by a frame in the **Daily movie**.
_Avoid_: Playback time, browser current time, frame number

**Movie frame time metadata**:
Machine-readable UTC timestamps used to map **Daily movie** playback to **Movie frame time**.
_Avoid_: Hard-coded FPS, encoded frame count, playback duration

**Spectrogram time axis**:
The absolute UTC time range represented by the x-axis of a **Daily spectrogram**.
_Avoid_: Percent progress, selected-date fraction, movie progress

**Spectrogram axis metadata**:
Machine-readable UTC start and end times for a **Spectrogram time axis**.
_Avoid_: Browser-inferred bounds, hard-coded plot bounds

**Spectrogram time indicator**:
A visual marker over the existing **Daily spectrogram** PNG at the current **Movie frame time**.
_Avoid_: Regenerated plot, interactive spectrogram

**Approximate movie frame time**:
A best-effort UTC timestamp used when exact **Movie frame time metadata** is unavailable or cannot be reconciled with the encoded **Daily movie**.
_Avoid_: Exact time, frame-accurate time

## Relationships

- A **Daily movie** has zero or more frames, and each frame has exactly one **Movie frame time**.
- A **Movie frame time** is the canonical time used to coordinate the **Daily movie** with the **Daily spectrogram**.
- **Movie frame time metadata** is the source of truth for deriving the current **Movie frame time** during playback.
- An **Approximate movie frame time** may be shown when exact mapping is unavailable, but it must be visibly marked as approximate.
- A **Movie frame time** is positioned on the **Daily spectrogram** by absolute UTC time on the **Spectrogram time axis**.
- **Spectrogram axis metadata** is the source of truth for drawing a time indicator on a **Daily spectrogram**.
- A **Spectrogram time indicator** is an overlay on the existing **Daily spectrogram** image.
- The **Spectrogram time axis** follows the solar observing window and changes with season and data availability.

## Example dialogue

> **Dev:** "Should the spectrogram indicator use the MP4 playback timestamp or the image timestamp represented by the current movie frame?"
> **Domain expert:** "Use **Movie frame time metadata** to derive the current **Movie frame time**, then place a **Spectrogram time indicator** by absolute UTC time on the **Spectrogram time axis** from **Spectrogram axis metadata**; playback time and frame number are only controls. If exact metadata is missing, show an **Approximate movie frame time** and label it clearly."

## Flagged ambiguities

- "time indicator" could mean browser playback time, frame number, or observation time — resolved: it means **Movie frame time** in UTC.
- "movie time mapping" could be derived from hard-coded FPS, encoded frame count, playback duration, or timestamp metadata — resolved: use **Movie frame time metadata**.
- "fallback movie time" could be hidden, shown as exact, or shown as approximate — resolved: show it only as an **Approximate movie frame time** with visible labeling.
- "position on the spectrogram" could mean percent progress through the movie or absolute time on the image — resolved: use absolute UTC time on the **Spectrogram time axis**.
- "spectrogram bounds" could be hard-coded, inferred from the PNG, or provided by the API — resolved: expose **Spectrogram axis metadata** from the backend.
- "adding a time indicator" could mean rebuilding the spectrogram plot or overlaying the existing image — resolved: draw a **Spectrogram time indicator** over the existing PNG.
- "daily" does not imply midnight-to-midnight for the **Spectrogram time axis** — resolved: use the actual solar observing window for that daily product.
