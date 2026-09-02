# Connect a service account for private Google Sheet imports (one-time)

No login/password of any Google account is needed for this. A "service
account" is just a robot Google identity with its own email address — you
share the sheet with that email, same as sharing it with a person.

## Step 1 — Create the service account

1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts
2. Pick a project at the top (or create one — any name is fine).
3. Click **+ Create Service Account** (top).
4. Give it any name, e.g. `sheet-reader`. Click **Create and Continue**.
5. Skip the "Grant access" and "Grant users access" steps — click **Done**.

## Step 2 — Download its key

1. In the service accounts list, click the one you just created.
2. Go to the **Keys** tab → **Add Key → Create new key**.
3. Choose **JSON** → **Create**. A `.json` file downloads to your computer.

## Step 3 — Share the Google Sheet with it

1. Open the downloaded `.json` file in any text editor (Notepad etc).
2. Find the line `"client_email": "...@....iam.gserviceaccount.com"` — copy that email.
3. Open the Google Sheet (as astalakshmi@gmail.com, the owner) → **Share**.
4. Paste that service account email in → set role **Viewer** → **Send**.

## Step 4 — Give the key to the server

1. Open the `.json` file, select all its contents, copy.
2. Render dashboard → your service → **Environment** → **Add Environment Variable**.
3. Key: `GOOGLE_SERVICE_ACCOUNT_JSON`
4. Value: paste the entire JSON contents.
5. Save — Render redeploys automatically.

Done. From now on, Google Sheet syncs will use this service account — only
sheets shared with its email will work, nothing is public.

### If it stops working later
Someone may have removed the service account's access to the sheet, or
deleted/revoked the key in Google Cloud Console. Re-share the sheet with the
same email (Step 3), or create a new key and redo Step 4.
