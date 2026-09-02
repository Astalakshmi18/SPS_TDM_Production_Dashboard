# Google Sheet (private) → Dashboard — Complete Guide

This covers everything end-to-end: what changed in the code, the Google
Cloud setup, local testing, and deploying to Render. Follow in order.

---

## Background — what this solves

- Dashboard reads project data from a Google Sheet.
- You do **not** want to make the sheet public ("Anyone with the link").
- Instead: sheet owner (astalakshmi@gmail.com) shares the sheet as
  **Viewer** with a second account (babydoll@gmail.com) — normal Google
  sharing, nothing special.
- The dashboard server signs in **as babydoll@gmail.com** (using saved
  credentials, not a live login each time) to download the sheet.

This is unrelated to the dashboard's own admin login/password — that's a
separate, already-solved topic (see the note at the very end).

---

## Part A — Google Cloud setup (you've already done this ✅)

Recap of what you did, for reference — no need to redo unless something breaks:

1. **console.cloud.google.com** → created a project.
2. **APIs & Services → OAuth consent screen** → clicked "Get Started" →
   filled App name / support email / Audience: External / contact email →
   created.
3. **Audience** tab → **Test users** → added `babydoll@gmail.com` (and one
   other email).
4. **Clients** tab → **Create Client**:
   - First tried "Desktop app" — this doesn't work with OAuth Playground,
     so a second client was made instead:
   - **Application type: Web application**, with **Authorized redirect
     URIs** = `https://developers.google.com/oauthplayground`
   - This gave you the real **Client ID** and **Client Secret** to use.
5. **developers.google.com/oauthplayground**:
   - Gear icon → "Use your own OAuth credentials" → pasted Client ID/Secret.
   - Scope box → pasted `https://www.googleapis.com/auth/drive.readonly` →
     Authorize APIs → signed in as **babydoll@gmail.com** → Allow.
   - Step 2 → "Exchange authorization code for tokens" → got a
     **Refresh token**.

**You should now have three values saved somewhere safe:**

| Value | Where it came from |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | Web application client (step 4) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Same client (step 4) |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | OAuth Playground step 2 |

Also confirm: the Google Sheet itself is shared with `babydoll@gmail.com`
as **Viewer** (Share button on the sheet, done by astalakshmi@gmail.com).

---

## Part B — Code changes (already done for you)

In the project zip you have from me, these files were changed:

- **`apps/projects/gsheet.py`** — now downloads the sheet using the OAuth
  refresh token (signs in as babydoll@gmail.com) instead of the old
  "anyone with the link" method. No other file needed to change — the
  function name/inputs/outputs stayed the same.
- **`config/settings.py`** — added 3 settings that read the values above
  from environment variables.
- **`render.yaml`** — declares the 3 env vars so Render's dashboard prompts
  for them.
- **`test_gsheet.py`** *(new)* — a standalone script to test the connection
  without running the full server. Used in Part C below.

You don't need to edit any of these — just follow Part C and Part D.

---

## Part C — Test locally first

Do this on your own computer, using the project folder extracted from the
zip I gave you.

### C1. Install Python requirements

Open a terminal/command prompt **inside the project folder** (the one with
`manage.py` in it) and run:

```bash
pip install -r requirements.txt
```

### C2. Create a `.env` file

In the same folder (next to `manage.py`), create a new file named exactly
`.env` (just that, no `.txt` at the end) with this content — replace with
your actual 3 values from Part A:

```
GOOGLE_OAUTH_CLIENT_ID=your_client_id_here
GOOGLE_OAUTH_CLIENT_SECRET=your_client_secret_here
GOOGLE_OAUTH_REFRESH_TOKEN=your_refresh_token_here
```

### C3. Run the quick test script

```bash
python test_gsheet.py "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit"
```

(Paste your actual sheet link, in quotes.)

**Expected output if it works:**
```
Trying to download: https://docs.google.com/spreadsheets/d/.../edit
SUCCESS - saved to media/uploads/gsheet_XXXXXXXX_XXXXXX.xlsx (12.3 KB)
The OAuth connection works. You can now run the full server.
```

**If it fails**, the error message will tell you what's wrong (e.g. sheet
not shared with babydoll@gmail.com, or a credential problem) — send me the
exact error and I'll help fix it.

### C4. (Optional) Run the full dashboard locally

Once C3 succeeds, you can test through the actual UI:

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000` in your browser, log in, and try adding/syncing
the project with the Google Sheet link — same as it'll behave once deployed.

---

## Part D — Deploy to Render

1. Push/upload this updated project code to wherever Render deploys from
   (your GitHub repo, or re-upload per your usual process).
2. Render dashboard → your service → **Environment**.
3. Add the same 3 variables as your `.env` file:
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `GOOGLE_OAUTH_REFRESH_TOKEN`
4. **Save Changes** → Render redeploys automatically (2–3 minutes).
5. Open the live dashboard, try the Google Sheet import/sync again.

---

## Reference — the earlier, separate topic (admin password)

Not related to any of the above, but from earlier in this conversation:
every redeploy runs `create_default_admin`, which **resets** the `admin`
user's password to `Swift_ProSys` automatically, every single time. If
login ever fails after a redeploy, that's the current password. (You said
you don't want to change this behavior right now, so it's left as-is — just
noting it here so it's not forgotten.)

---

## If something breaks later

- **"Access blocked" / login fails on OAuth Playground** → the OAuth client
  used with the Playground must be **Web application** type with redirect
  URI `https://developers.google.com/oauthplayground`. A "Desktop app"
  client will not work there.
- **Sheet download fails with "access denied"** → check the sheet is still
  shared with babydoll@gmail.com as Viewer, and that access to the app
  wasn't revoked at https://myaccount.google.com/permissions.
- **Refresh token stops working** → redo Part A, step 5 (OAuth Playground)
  to get a new refresh token, and update it in both `.env` (local) and
  Render's Environment settings.
