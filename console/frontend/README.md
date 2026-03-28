# Frontend

The dashboard is a React + Vite app.

## Auth Environment

Create a frontend `.env` file from `.env.example` and set:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_API_BASE_URL`

The browser only talks to Supabase for Google sign-in. Product data should still go through the backend API.

This frontend persists browser auth through Supabase, so normal page refreshes should keep users signed in until they sign out or the session becomes invalid.
