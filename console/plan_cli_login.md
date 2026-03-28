Build CLI login as a website-mediated authentication flow. The CLI should not complete browser OAuth on its own. The user should open your backend/app website, sign in there, enter a code shown by the CLI, and the backend should approve the CLI session and issue backend-owned CLI tokens.

Goal
Replace the current localhost browser callback approach with a backend-controlled pairing flow where:

- CLI starts a login request with the backend
- backend creates a short code for the user
- user opens the backend/app website and signs in there
- user enters that code on the website
- backend mints CLI-specific tokens
- CLI stores only its own access and refresh tokens

This keeps the website/app as the interactive sign-in surface and the backend as the trust boundary.

Recommended Model
Use a device-flow style pairing process with website verification:

1. CLI calls backend to start login
2. backend creates a short-lived pending auth record
3. CLI shows a short code and a website URL
4. user opens the website
5. if needed, user signs in on the website
6. user enters the short code on the website
7. backend matches that code to the pending CLI login and approves it
8. CLI polls backend until approved
9. backend returns CLI access token and refresh token
10. CLI stores those securely in keyring

Do not pass the website/app's own access token directly into the CLI. The website should approve the request, not donate its token.

Alternative
If later you want a native app deep link too, you can add it as a convenience. But the primary design should be:

- CLI shows code
- user opens website
- user signs in
- user enters code
- backend approves CLI

Backend Responsibilities

Data Model
Add a backend-owned store for pending CLI auth sessions. Each pending session should include:

- `id`
- `device_code`
- `user_code`
- `status` with values like `pending`, `approved`, `denied`, `expired`, `consumed`
- `requested_at`
- `expires_at`
- `approved_at`
- `denied_at`
- `last_polled_at`
- `client_name` or device label
- `requested_scopes` if you need scoped CLI tokens later
- `approved_by_user_id`
- `consumed_at`
- optional metadata like IP, platform, CLI version

The backend must enforce expiry and single-use semantics.

Endpoints
Add these endpoints:

`POST /cli/auth/start`
- public endpoint used by the CLI
- creates a pending auth request
- returns:
  - `device_code`
  - `user_code`
  - `verification_url`
  - `expires_in`
  - `interval`
  - optional `pairing_id`

`GET /cli/login`
- website page for the user
- if the user is not signed in, redirect to sign-in first
- after sign-in, show a form where the user can enter the CLI code

`POST /cli/auth/verify`
- authenticated website/app endpoint
- requires the user to already be signed in
- body includes `user_code`
- backend verifies the request is still pending and not expired
- backend maps `user_code` to the secure pending request
- backend marks it approved for that authenticated user

`POST /cli/auth/deny`
- authenticated website/app endpoint
- denies a pending request explicitly

`POST /cli/auth/token`
- public endpoint used by the CLI for polling
- body includes `device_code`
- while pending, returns a pending response
- once approved, returns:
  - CLI access token
  - CLI refresh token
  - token type
  - expires_in or expires_at
  - user summary needed by CLI
- once consumed, further calls fail

`POST /cli/auth/refresh`
- refreshes CLI tokens
- takes CLI refresh token
- rotates refresh token if possible

`POST /cli/auth/logout`
- optional but recommended
- revokes the CLI refresh token and invalidates active CLI session state

Token Issuance
Backend should mint CLI-specific tokens, not reuse app session tokens.

Requirements:

- use a separate audience or token type for CLI sessions
- include claims that identify this as a CLI token
- allow the backend to revoke CLI refresh tokens independently
- keep access token lifetime short
- rotate refresh tokens on refresh if your auth stack supports it

If Supabase remains the identity provider, the backend can still trust Supabase for user identity, but the backend should own the CLI login approval and token issuance layer.

Approval Rules
The backend must:

- reject expired pending requests
- reject already consumed requests
- allow only one approval outcome
- bind approval to the currently authenticated website/app user
- optionally display device name and CLI version before approval
- log all approvals and denials for audit

Polling Rules
The backend should:

- return `authorization_pending` while waiting
- return `slow_down` if the CLI polls too aggressively
- return `expired_token` when the login window is over
- return success exactly once for a valid approved request

Security Requirements

- `device_code` must be high-entropy and never guessable
- `user_code` can be short and human-friendly, but must map to the secure request server-side
- `device_code` must expire quickly, ideally 5 to 10 minutes
- `user_code` must be single-use
- approved requests must be consumed exactly once
- refresh tokens must be revocable
- audit log should capture start, approve, deny, consume, refresh, logout
- rate limit start, approve, and token polling endpoints
- show website/app user which CLI/device they are approving

Frontend Responsibilities

Website/App UX
The website becomes the main login approval surface. If you also have an app, it can reuse the same backend flow.

At minimum the website needs:

- a page at `verification_url`
- sign-in support if the user is not already authenticated
- input for `user_code`
- an approval screen that shows:
  - requested CLI/device name
  - expiration time
  - account currently signed in
  - approve and deny actions

Recommended flow:

1. user runs `envbasis login`
2. CLI shows a code and a link
3. user opens the website
4. if not already signed in, website asks them to sign in
5. user enters the code
6. website resolves the pending CLI request
7. website shows approval details
8. user taps approve
9. website calls backend `POST /cli/auth/verify`
10. CLI polling completes

Frontend Edge Cases
The website/app should handle:

- user not signed in
- invalid code
- expired code
- already approved
- already denied
- already used

The website/app should show exact user-facing states for each case instead of generic errors.

Website URL

The main URL should be something like:

- `https://app.example.com/cli/login`

Optional improvement:

- if the CLI can include the code in the URL, the page can pre-fill it
- example: `https://app.example.com/cli/login?code=ABCD-EFGH`

Native app deep links can be added later, but they are not required for the primary design.

CLI Responsibilities

`envbasis login`
Replace the existing Supabase browser flow with:

1. call `POST /cli/auth/start`
2. display:
   - verification URL
   - short `user_code`
   - waiting status
3. optionally open the verification URL in the browser
4. poll `POST /cli/auth/token`
5. once approved, save returned CLI session into keyring
6. call backend `GET /auth/me` if you still want a final session validation step

`envbasis logout`
CLI should:

- clear local keyring session
- optionally call backend `POST /cli/auth/logout` first if a refresh token exists

`envbasis whoami`
No major change. It should continue to:

- load local session
- refresh if needed
- call backend `GET /auth/me`

Local Storage
CLI should continue storing:

- access token
- refresh token
- token type
- expires_at
- user_id
- email

Store this in OS keyring, not in `.envbasis.toml`.

Config
The CLI no longer needs direct Supabase public login configuration for the normal login path.

Keep only:

- backend API base URL
- project/environment defaults

Remove the CLI's dependence on:

- `supabase_url`
- `anon_key`
- `redirect_url`
- `oauth_provider`

for login, unless they are still needed elsewhere.

Suggested Backend Response Shapes

`POST /cli/auth/start`

```json
{
  "device_code": "secure-random-long-string",
  "user_code": "ABCD-EFGH",
  "verification_url": "https://app.example.com/cli/login",
  "expires_in": 600,
  "interval": 5
}
```

`POST /cli/auth/token` pending

```json
{
  "status": "pending",
  "error": "authorization_pending"
}
```

`POST /cli/auth/token` approved

```json
{
  "status": "approved",
  "access_token": "cli-access-token",
  "refresh_token": "cli-refresh-token",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "user_123",
    "email": "dev@example.com"
  }
}
```

Implementation Order

Phase 1: Backend

- add pending CLI auth storage
- add start, verify, deny, token, refresh endpoints
- add audit events
- add revocation and expiry handling

Phase 2: Frontend/Website

- add website login page
- add code entry form
- add signed-in approval screen
- add approve and deny actions
- show device details and expiration

Phase 3: CLI

- replace current `login` flow with `start + poll`
- keep keyring session storage
- keep `whoami` and refresh behavior
- update `logout` to revoke backend refresh token if available

Phase 4: Cleanup Before Launch

- remove localhost callback listener
- remove direct Supabase authorize/token exchange from CLI
- remove unused Supabase login config from CLI docs and config

Testing Plan

Backend tests:

- start creates pending request
- approve binds authenticated user
- deny blocks completion
- expired requests cannot be approved or consumed
- polling returns pending before approval
- polling returns tokens once after approval
- second consume attempt fails
- refresh rotates or validates refresh token correctly
- logout revokes CLI session

Frontend tests:

- code entry flow
- website code entry flow
- optional code pre-fill from query param
- signed-out user redirected to sign in then back to approval
- approve and deny states
- expired and invalid code states

CLI tests:

- login start request success
- login polling success
- login timeout/expiry handling
- denied login handling
- session persistence to keyring
- refresh using backend refresh endpoint
- logout clears local session and handles backend revoke errors

Launch Note
This flow has not launched yet, so you do not need a backwards-compatibility migration plan for existing users.

Recommended pre-launch approach:

- build only the new backend/website code-entry flow
- implement the website verification experience
- implement the CLI against the new backend flow
- remove the old localhost callback implementation before launch
- remove Supabase login config from the CLI before launch

Bottom Line
The backend should own CLI session issuance.
The website/frontend should own the interactive user approval.
The CLI should only initiate, poll, store its own tokens, and use them.

That is the clean and secure shape for “my CLI shows a code, the user opens my website, enters the code, and the backend lets the CLI in.”
