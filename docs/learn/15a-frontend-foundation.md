# Step 15a: Frontend foundation

## What was built

The frontend now has a responsive Next.js App Router shell, a light/dark design
system, reusable accessible UI components, login and registration screens, and
placeholder routes for the study areas. The app protects its routes, restores
sessions, shows a user's public handle, and exposes account details and a theme
toggle on Settings.

The frontend API uses generated TypeScript declarations from FastAPI's OpenAPI
schema and `openapi-fetch`. A fetch-based SSE helper supports authenticated
stream requests and event parsing. Frontend tests mock the API; they do not
contact a running backend.

## Why it was built

A common shell and design system give later study features a consistent place to
live. A typed API boundary catches request and response mismatches early. Keeping
access tokens in memory limits their lifetime, while refresh tokens allow a
returning user to restore a session.

For this step, the refresh token is persisted in `localStorage` with guarded
access. This is a documented client-side storage trade-off: moving it to an
httpOnly cookie is planned for the security hardening step.

## How it works

- The App Router groups protected study pages under a shared shell. The route
  guard sends unauthenticated visitors to `/login` with their original path;
  after login, the app returns them there.
- Login and registration call typed auth operations. Access tokens stay in
  module memory; refresh tokens are stored in `localStorage`. On load, the app
  exchanges a saved refresh token for a new token pair. Concurrent 401
  responses share that refresh request, and each original request is retried
  only once.
- `scripts/gen-api.mjs` imports the backend app and writes its OpenAPI schema
  without starting an HTTP server. `openapi-typescript` generates the committed
  declarations consumed by the typed client.
- React Query provides a 30-second stale time and avoids retrying client errors.
  `useMe` exposes the current in-memory user profile to app screens.
- SSE uses `fetch` so it can include the Authorization header. A
  `ReadableStream` reader and `TextDecoder` preserve partial lines between
  chunks and join multi-line `data:` fields. An `AbortController` stops the
  stream when its consumer unmounts.

## Key syllabus concept

The frontend is a client-server system. Types generated from an API contract
make the boundary explicit, while session state and retry behavior coordinate
multiple requests without treating a failed response as successful data.

## Viva questions and answers

1. **Why does the access token stay in memory?**
   It avoids persisting the short-lived credential in browser storage, reducing
   how long it remains available to client-side code.

2. **Why is the refresh token still in localStorage for this step?**
   It lets the browser restore a session across reloads. This is a trade-off;
   moving it to an httpOnly cookie is planned for the security hardening step.

3. **How does the API client handle concurrent expired requests?**
   They await one shared refresh promise, then each retries its own request
   once with the new access token.

4. **Why use fetch rather than EventSource for SSE?**
   Fetch allows the request to carry the Authorization header and exposes a
   readable response stream.

5. **How does the SSE parser handle chunk boundaries?**
   It keeps incomplete text in a buffer until a line ending arrives, then
   combines all `data:` lines in an event with newline separators.
