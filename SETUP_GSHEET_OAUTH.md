# Connect babydoll@gmail.com for private Google Sheet imports (one-time)

No service account keys needed — you'll just log in as babydoll@gmail.com
once in the browser to authorize it, and that authorization is remembered.

## Step 1 — Create an OAuth Client ID

1. Go to https://console.cloud.google.com/apis/credentials
   (use the same project you already created).
2. If it asks you to configure a "consent screen" first: click that, choose
   **External**, fill only the required fields (App name, your email in the
   two email boxes), click **Save and Continue** through every remaining
   page without changing anything, until you reach **Back to Dashboard**.
3. On the **Test users** page (one of those steps), click **+ Add Users**
   and add `babydoll@gmail.com`. Save and continue.
4. Now go back to https://console.cloud.google.com/apis/credentials
5. Click **+ Create Credentials** (top) → **OAuth client ID**.
6. Application type: **Desktop app**. Name: anything, e.g. `sheet-reader`.
7. Click **Create**. A popup shows a **Client ID** and **Client secret** —
   copy both somewhere safe (Notepad).

## Step 2 — Get a refresh token, logged in as babydoll@gmail.com

1. Go to https://developers.google.com/oauthplayground
2. Click the **gear icon** (top-right) → tick **"Use your own OAuth
   credentials"** → paste the Client ID and Client secret from Step 1.
3. On the left, under "Input your own scopes", paste:
   ```
   https://www.googleapis.com/auth/drive.readonly
   ```
   Click **Authorize APIs**.
4. Sign in with **babydoll@gmail.com** (not astalakshmi). If you see an
   "unverified app" warning, click **Advanced** → **Go to (app name)
   (unsafe)** → **Allow**. (This warning is normal and expected — it's your
   own app, just not submitted for Google's public review.)
5. Back on the Playground, click **Exchange authorization code for tokens**.
6. A **Refresh token** appears on the right — copy it.

## Step 3 — Give these to the server

Render dashboard → your service → **Environment** → add three variables:

| Key | Value |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | Client ID from Step 1 |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Client secret from Step 1 |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | Refresh token from Step 2 |

Save — Render redeploys automatically. Done. From now on, Google Sheet syncs
read as babydoll@gmail.com — only sheets shared with that account will work.

### If it stops working later
If babydoll@gmail.com's access is removed from the sheet, or the app's
access is revoked at https://myaccount.google.com/permissions, syncing will
fail with a clear error — just redo Step 2.
