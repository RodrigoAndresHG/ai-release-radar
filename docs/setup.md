# Setup Guide

This guide explains how to configure AI Release Radar for GitHub Actions, Telegram, Cloudflare Worker routing, and local image assets.

Do not commit real secrets to the repository.

## GitHub Secrets

In the GitHub repository:

1. Open `Settings`.
2. Go to `Secrets and variables`.
3. Open `Actions`.
4. Add repository secrets.

Required:

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

The workflows read these secrets as environment variables.

## Telegram Bot

Create the bot:

1. Open Telegram.
2. Start a chat with `@BotFather`.
3. Send `/newbot`.
4. Choose a bot name and username.
5. Copy the token.
6. Save it as `TELEGRAM_BOT_TOKEN`.

Get the chat id:

1. Send any message to the bot.
2. Open:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
```

3. Copy `chat.id`.
4. Save it as `TELEGRAM_CHAT_ID`.

For group chats, add the bot to the group and use the group `chat.id`.

## GitHub Personal Access Token

The Cloudflare Worker needs permission to trigger GitHub Actions.

Create a fine-grained GitHub token with access to the repository and permission to run Actions workflows. Store it only in Cloudflare Worker secrets.

Suggested Worker secret names:

```text
GITHUB_TOKEN
GITHUB_OWNER
GITHUB_REPO
GITHUB_REF
```

`GITHUB_REF` is usually the branch name, for example:

```text
main
```

Do not store this token in the repository.

## Cloudflare Worker

The Worker acts as the Telegram webhook receiver and GitHub Actions dispatcher.

Expected behavior:

1. Receive Telegram webhook payload.
2. Read the message text.
3. Accept only valid choices: `1`, `2`, `3`.
4. Call GitHub Actions `workflow_dispatch` for:

```text
.github/workflows/radar-content.yml
```

5. Pass the choice:

```json
{
  "ref": "main",
  "inputs": {
    "choice": "2"
  }
}
```

The Worker should reject unrelated messages or ignore them safely.

## Telegram Webhook

After deploying the Worker, register it as the Telegram webhook:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=<WORKER_URL>
```

Useful checks:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo
```

If you switch back to polling, remove the webhook:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/deleteWebhook
```

## GitHub Actions

Scheduled workflows:

- `radar-brief.yml`: daily at `12:00 UTC`.
- `radar-content.yml`: daily at `12:10 UTC`.

Manual run:

1. Open GitHub Actions.
2. Select `AI Release Radar Brief` or `AI Release Radar Content`.
3. Click `Run workflow`.
4. For content, optionally enter `choice` as `1`, `2`, or `3`.

## Local Development

Install:

```bash
pip install -r requirements.txt
```

Create `.env`:

```text
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
RADAR_MODE=brief
GOOGLE_DRIVE_FOLDER_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=
```

Run brief:

```bash
RADAR_MODE=brief python daily_brief.py
```

Run content:

```bash
RADAR_MODE=content python daily_brief.py
```

Run test mode:

```bash
TEST_MODE=1 RADAR_MODE=brief python daily_brief.py
```

## Assets

Expected folders:

```text
assets/brand/
assets/logos/
```

Optional personal avatar:

```text
assets/brand/rodrigo.png
```

Optional local logos:

```text
assets/logos/openai.png
assets/logos/anthropic.png
assets/logos/google.png
assets/logos/gemini.png
assets/logos/aws.png
assets/logos/claude.png
```

If these assets do not exist, image generation still works. Pillow simply omits the missing logos/avatar.

## Verification

Syntax check:

```bash
python3 -m py_compile daily_brief.py
```

Check workflows manually from the GitHub Actions UI before relying on the schedule.
