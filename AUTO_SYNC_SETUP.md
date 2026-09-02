# Auto-sync every 30 minutes — privacy-first setup

This does the sync **entirely inside your own server** — no third-party
service ever sees your data, your OAuth token, or even that syncing is
happening. Only a plain "keep-alive" ping (which sees nothing but "ok")
goes to an outside service, and only because Render's free plan needs
*some* incoming traffic to stay awake.

## How it works

- `apps/projects/scheduler.py` — runs a timer inside the same server
  process. Every `AUTO_SYNC_INTERVAL_MINUTES` (default 30), it directly
  calls the same sync function "Sync Now" uses, for every project linked
  to a Google Sheet. Nothing is sent anywhere external to do this.
- `apps/projects/apps.py` — starts that timer when the server boots.
- `/health/` — a new, plain, public URL that just returns `"ok"`. It
  carries no token and no data — it exists only so a generic uptime
  monitor can ping it to stop Render from putting the free service to
  sleep after ~15 minutes of no traffic.

## Step 1 — Turn the scheduler on

Render dashboard → your service → **Environment**, confirm these are set
(already added to `render.yaml`, but verify after deploy):

| Key | Value |
|---|---|
| `ENABLE_AUTO_SYNC_SCHEDULER` | `True` |
| `AUTO_SYNC_INTERVAL_MINUTES` | `30` |

(Along with the `GOOGLE_OAUTH_*` variables from earlier, which the sync
itself depends on.)

Deploy/redeploy so these take effect.

## Step 2 — Keep the free service awake (privacy-neutral)

Render's free web services spin down after ~15 minutes idle, which would
also pause the in-process timer. Fix: a free uptime monitor pings your
`/health/` URL every 10–14 minutes — nothing else.

Using **UptimeRobot** (free):

1. Go to https://uptimerobot.com and create a free account.
2. **+ Add New Monitor**.
3. Monitor type: **HTTP(s)**.
4. Friendly name: anything, e.g. `Dashboard keep-alive`.
5. URL: `https://YOUR-APP.onrender.com/health/`
6. Monitoring interval: **5 minutes** (well under Render's ~15 min sleep
   window).
7. Save.

That's the only thing that leaves your server going forward: a plain GET
to `/health/`, and a plain `"ok"` back. No token, no project data, no sync
capability is exposed by this URL.

## Step 3 — Verify it's working

- Check Render's **Logs** tab a few minutes after deploy — you should see
  a line like `Auto-sync scheduler started (every 30 minutes).`
- After ~30 minutes, look for `Auto-sync run complete: N synced, 0 failed...`
- Or just check a project's dashboard numbers update on their own without
  anyone clicking "Sync Now".

## Notes

- **Single web service instance only.** This timer runs inside one
  process. If you ever scale the Render service to more than one instance,
  every instance would run its own timer and you'd get duplicate syncs —
  don't scale this service beyond 1 instance without changing this design
  first (ask me if that becomes relevant).
- The old token-protected `/projects/cron/sync-all/<token>/` endpoint from
  before is still in the code as an optional manual/backup trigger, but you
  don't need any external service calling it anymore — the in-process
  scheduler replaces that need.
- If you'd rather not touch the `/health/` endpoint or use any uptime
  monitor, the auto-sync will still run every 30 minutes *whenever the
  service happens to be awake* — just not reliably if it's gone to sleep
  for hours with nobody visiting the site.
