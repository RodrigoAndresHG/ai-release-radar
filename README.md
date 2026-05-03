# AI Release Radar

AI Release Radar is a release-first agent that monitors official AI product and model signals, ranks the most relevant launches, and sends the daily radar to Telegram.

The system is optimized for Rodrigo Hered IA content workflows: first it sends a short Top 3, then it turns the selected release into a publish-ready content pack and an Instagram/TikTok cover image.

## What It Detects

- New OpenAI, ChatGPT, API, GPT, and Sora releases.
- New Anthropic, Claude, and Claude Code releases.
- New Google, Gemini, DeepMind, and Vertex AI releases.
- Official AI apps and product launches.
- API, SDK, changelog, developer tooling, and release note updates.
- Pricing, availability, rollout, preview, GA, and deprecation changes.
- Features involving agents, audio, video, coding, multimodality, realtime, function calling, and tools.

The scoring intentionally penalizes CEO opinions without releases, AGI predictions, rumors, generic analysis, recycled news, and vague future-of-AI posts.

## Architecture

High-level flow:

```text
Telegram
  -> Cloudflare Worker
  -> GitHub Actions
  -> daily_brief.py
  -> OpenAI API
  -> Telegram
```

Main components:

- `daily_brief.py`: fetches releases, scores them, selects the daily insight, generates content, creates images, and sends Telegram messages.
- GitHub Actions: runs the scheduled `brief` and `content` modes.
- Telegram Bot: receives the Top 3, content pack, and final image.
- Cloudflare Worker: external webhook layer for manual Telegram selection, typically mapping replies `1`, `2`, or `3` to a GitHub Actions `workflow_dispatch` run.
- OpenAI API: generates the textual content and the text-free visual background.
- Pillow: composes all final image text, diagrams, avatar, layout, and branding locally.

More detail: [docs/architecture.md](docs/architecture.md).

## Daily Flow

The intended daily flow is:

1. `07:00 America/Guayaquil` / `12:00 UTC`: `RADAR_MODE=brief` sends the Top 3 releases to Telegram.
2. The brief run saves `selected_release.json` with the Top 3 and defaults the selected release to `#1`.
3. `07:10 America/Guayaquil` / `12:10 UTC`: `RADAR_MODE=content` generates content automatically for `#1`.
4. Manual override: selecting `1`, `2`, or `3` from Telegram can trigger the content workflow with that choice through the Cloudflare Worker.

The content workflow also supports manual GitHub execution with the `choice` input.

## GitHub Actions

Workflows:

- `.github/workflows/radar-brief.yml`
  - Runs daily at `12:00 UTC`.
  - Supports `workflow_dispatch`.
  - Sets `RADAR_MODE=brief`.
  - Sends the Top 3 and caches `selected_release.json`.

- `.github/workflows/radar-content.yml`
  - Runs daily at `12:10 UTC`.
  - Supports `workflow_dispatch` with optional `choice`.
  - Sets `RADAR_MODE=content`.
  - Uses `selected_release.json` so the content aligns with the brief.
  - Generates the text pack and image, then sends both to Telegram.

## Telegram Bot

Telegram is used for delivery:

- `sendMessage` sends the brief or content text.
- `sendPhoto` sends `output/instagram_release.png` when content mode generates an image.
- If image sending fails, the workflow does not crash; the script attempts to send a text warning instead.

To create the bot:

1. Open Telegram and start `@BotFather`.
2. Send `/newbot`.
3. Follow the instructions.
4. Save the token as `TELEGRAM_BOT_TOKEN`.
5. Get the destination chat id and save it as `TELEGRAM_CHAT_ID`.

## Cloudflare Worker

The Cloudflare Worker is the external bridge for manual Telegram selection.

Expected role:

- Receive Telegram webhook updates.
- Parse messages like `1`, `2`, or `3`.
- Trigger GitHub Actions `workflow_dispatch` for `radar-content.yml`.
- Pass the selected number as the `choice` input.

The Worker code is not required inside this repository for the Python agent to run. Setup details are in [docs/setup.md](docs/setup.md).

## Image Generation For Instagram

The image system is intentionally split into two stages:

1. OpenAI Images generates only a dark premium abstract background with no text, no letters, no logos, and no marks.
2. Pillow composes the final 1080x1080 image locally:
   - title
   - glass-effect diagram container
   - FLOW / BEFORE_AFTER / ARCHITECTURE templates
   - local logos if available
   - circular Rodrigo avatar if available
   - exact brand text: `Rodrigo Hered IA`
   - subtitle: `AI Builder / CIO`

This prevents image-model typos in provider names, brand text, diagram labels, and release titles.

Detailed image docs: [docs/image-system.md](docs/image-system.md).

## Assets

Optional local assets:

```text
assets/brand/rodrigo.png
assets/logos/openai.png
assets/logos/anthropic.png
assets/logos/google.png
assets/logos/gemini.png
assets/logos/aws.png
assets/logos/claude.png
```

If assets are missing, the system continues without failing.

Generated outputs:

```text
output/background.png
output/instagram_release.png
selected_release.json
history_brief.json
history_content.json
```

## Variables And Secrets

Required for GitHub Actions and local runs:

```text
OPENAI_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Optional:

```text
GOOGLE_DRIVE_FOLDER_ID
GOOGLE_SERVICE_ACCOUNT_JSON
```

Runtime variables:

```text
RADAR_MODE=brief | content
SELECT_CHOICE=1 | 2 | 3
TEST_MODE=1
```

Cloudflare Worker secrets usually include:

```text
TELEGRAM_BOT_TOKEN
GITHUB_TOKEN
GITHUB_OWNER
GITHUB_REPO
GITHUB_REF
```

Do not commit real secret values.

## Local Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create `.env` from `.env.example`:

```text
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
RADAR_MODE=brief
GOOGLE_DRIVE_FOLDER_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=
```

Run:

```bash
python daily_brief.py
```

Test mode:

```bash
TEST_MODE=1 RADAR_MODE=brief python daily_brief.py
```

## What It Does Not Do

- It does not invent releases, prices, dates, benchmarks, or availability.
- It does not scrape aggressively.
- It does not publish automatically to social platforms.
- It does not rely on AI-generated text inside images.
- It does not require logos or avatar assets to run.
