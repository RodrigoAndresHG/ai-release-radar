# AI Product & Model Release Radar

AI Product & Model Release Radar is a small Python agent that monitors AI product and model release signals, selects the strongest relevant item, generates a short creator/builder-friendly brief with OpenAI, and sends it to Telegram.

It is designed to run locally or on GitHub Actions once per day.

## What It Detects

- New OpenAI, ChatGPT, API, and Sora model or product releases
- New Anthropic, Claude, and Claude Code releases
- New Google, Gemini, DeepMind, and Vertex AI releases
- Official AI apps and product launches
- API, SDK, changelog, and developer tooling updates
- Pricing, availability, rollout, beta, preview, GA, and deprecation changes
- Important features such as agents, audio, video, coding, multimodal support, realtime, function calling, and tools

The agent uses release-first scoring, so official changelogs and concrete availability changes rank higher than commentary or generic AI news.

## What It Does Not Do

- It does not invent details, prices, dates, benchmarks, or availability.
- It does not scrape websites aggressively.
- It does not publish automatically to social media.
- It does not treat CEO opinions, AGI predictions, rumors, or analysis articles as releases unless there is a concrete launch, model, API, pricing, availability, or feature change.

## Sources Monitored

The script currently checks:

- OpenAI News RSS
- Claude Code changelog RSS
- Vertex AI Generative AI release notes feed
- Google Gemini product updates RSS
- Google DeepMind blog RSS
- Google News RSS fallback queries focused on release notes, changelogs, new models, Gemini API, Vertex AI, Claude Code, ChatGPT, and OpenAI API

Some official release pages do not expose a stable RSS feed yet, so they are tracked as code TODOs instead of using fragile scraping: OpenAI API changelog, ChatGPT release notes, Anthropic API release notes, Claude release notes, and Gemini API release notes.

## Create A Telegram Bot

1. Open Telegram and start a chat with `@BotFather`.
2. Send `/newbot`.
3. Follow the prompts to choose a name and username.
4. Copy the bot token. This becomes `TELEGRAM_BOT_TOKEN`.
5. Start a chat with your new bot or add it to a group/channel.
6. Get the chat ID. A common method is to send a message to the bot, then open:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
```

Use the returned `chat.id` as `TELEGRAM_CHAT_ID`.

## Configure GitHub Secrets

In your GitHub repository:

1. Go to `Settings`.
2. Open `Secrets and variables`.
3. Open `Actions`.
4. Add these repository secrets:

```text
OPENAI_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Do not commit a real `.env` file or real secret values.

## Run Manually In GitHub Actions

1. Go to the `Actions` tab in GitHub.
2. Select `AI Release Radar`.
3. Click `Run workflow`.
4. Choose the branch.
5. Click `Run workflow`.

The workflow installs Python dependencies and runs:

```bash
python daily_brief.py
```

## Daily Schedule

The workflow is configured to run daily at 12:00 UTC:

```yaml
schedule:
  - cron: "0 12 * * *"
```

GitHub scheduled workflows run automatically on the default branch after the workflow file is merged or pushed there. You can disable or re-enable the workflow from the GitHub Actions UI.

## Local Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local `.env` file using `.env.example` as a guide:

```text
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Then run:

```bash
python daily_brief.py
```
