# hfaf

A small scheduled polling utility. It runs on a timer via GitHub Actions,
queries an HTTP API, applies a couple of filters, and sends a push
notification (via [ntfy.sh](https://ntfy.sh)) when something matches. A tiny
`state.json` file is committed back each run so it doesn't repeat itself.

No API keys or accounts required.

## Setup

1. **Add two secrets.** Settings → Secrets and variables → Actions → New
   repository secret:
   - `NTFY_TOPIC` — a unique, hard-to-guess value (ntfy topics are public by
     name, so treat it like a password).
   - `SOURCE_URL` — the base source endpoint to query (the radius is appended
     to it automatically).
2. **Subscribe.** Install the [ntfy](https://ntfy.sh) app on your phone and add
   that same topic, or watch `https://ntfy.sh/<your-topic>` in a browser.
3. **Run it.** The workflow is on a schedule; you can also trigger it manually
   from the **Actions** tab (**Run workflow**).

## Tuning

The behaviour is controlled by a few plain constants at the top of `poll.py`
(a search radius, a threshold, and a repeat-suppression cooldown). Adjust them
to taste and commit the change.

## Local run

```bash
NTFY_TOPIC=your-topic python poll.py
```
