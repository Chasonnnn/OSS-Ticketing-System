# Google Workspace Journal Setup

This guide configures Google Workspace journaling for OSS Ticketing ingestion.

## 1. Create a Dedicated Journal Mailbox
- Create a mailbox used only for journal intake (example: `journal@yourdomain.com`).
- Do not use this mailbox for outbound sending.

## 2. OAuth App Configuration
- In Google Cloud, create OAuth credentials for the API.
- Add redirect URI:
  - `${API_BASE_URL}/mailboxes/gmail/oauth/callback`
- Configure `.env`:
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_CLIENT_SECRET`

## 3. Connect the Journal Mailbox
1. Log in to the web UI as admin.
2. Open `/mailboxes`.
3. Run “Connect Gmail journal mailbox”.
4. Verify connectivity status and scopes.

## 4. Loop-Prevention Checklist (Required)
- Exclude the journal mailbox from any journaling/mirroring destination rules.
- Exclude any relay/sending mailbox used for outbound replies.
- Do not BCC outbound traffic back into the same mirror path.
- Keep recipient allowlist strict to avoid catch-all spam floods.

## 5. Validate Ingestion
- Start API + worker.
- Enqueue history sync:
  - `POST /mailboxes/{mailbox_id}/sync/history`
- Use Ops dashboard:
  - `/ops` -> Mailbox Sync Dashboard
  - Check lag, queued/running jobs, and errors.

