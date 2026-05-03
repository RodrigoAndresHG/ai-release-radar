# Architecture

AI Release Radar connects Telegram, Cloudflare Worker, GitHub Actions, `daily_brief.py`, OpenAI APIs, and Telegram delivery.

## System Flow

```text
Telegram
  -> Cloudflare Worker
  -> GitHub Actions
  -> daily_brief.py
  -> OpenAI API
  -> Telegram
```

## Components

### Telegram

Telegram is the user-facing interface.

It receives:

- the daily Top 3 release brief
- the publish-ready content pack
- the generated Instagram image

For manual selection, Telegram can send `1`, `2`, or `3` to the Cloudflare Worker.

### Cloudflare Worker

The Worker is the external webhook bridge.

Expected responsibilities:

- receive Telegram webhook updates
- validate that the message is a valid release choice
- map `1`, `2`, or `3` to the `choice` input
- call GitHub Actions `workflow_dispatch`
- trigger `.github/workflows/radar-content.yml`

The Worker should not contain OpenAI logic, scoring logic, image logic, or Telegram formatting logic. It only routes selection intent to GitHub Actions.

### GitHub Actions

There are two workflows.

`radar-brief.yml`:

- runs at `12:00 UTC`
- sets `RADAR_MODE=brief`
- runs `python daily_brief.py`
- sends the Top 3 to Telegram
- stores `selected_release.json` in the workflow cache

`radar-content.yml`:

- runs at `12:10 UTC`
- sets `RADAR_MODE=content`
- accepts optional `choice`
- restores `selected_release.json`
- runs `python daily_brief.py`
- sends the content pack and image to Telegram

### `daily_brief.py`

The Python agent handles the core system:

- fetches official and fallback release sources
- scores release candidates
- filters out low-value or non-release items
- builds a Top 3
- persists `selected_release.json`
- generates content with OpenAI text models
- generates a text-free image background with OpenAI Images
- composes the final image with Pillow
- sends Telegram text and photo

### OpenAI API

The OpenAI API is used in two separate ways:

- text generation for the creator-ready content pack
- image background generation with no text

The final image text is not produced by OpenAI Images.

### Telegram Delivery

`daily_brief.py` sends:

- `sendMessage` for text
- `sendPhoto` for `output/instagram_release.png`

Image sending is non-blocking for the workflow. If photo delivery fails, the script attempts to send a warning message instead.

## Daily Sequence

```text
07:00 America/Guayaquil
  GitHub Actions brief
  -> daily_brief.py
  -> Top 3 to Telegram
  -> selected_release.json saved

07:10 America/Guayaquil
  GitHub Actions content
  -> daily_brief.py
  -> selected release loaded
  -> content generated
  -> image generated
  -> Telegram text + photo
```

Manual choice:

```text
Telegram reply: 2
  -> Cloudflare Worker
  -> GitHub Actions workflow_dispatch
  -> radar-content.yml with choice=2
  -> daily_brief.py SELECT_CHOICE=2
  -> content for release #2
```

## Persistence

Files generated at runtime:

```text
selected_release.json
history_brief.json
history_content.json
output/background.png
output/instagram_release.png
```

`selected_release.json` keeps the Top 3 for the day and allows content mode to reuse the same release selected by brief mode.
