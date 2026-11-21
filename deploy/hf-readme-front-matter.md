---
title: Engineering AI Assistant
emoji: 🧭
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Engineering AI Assistant

Decision-support chat for mechanical and process engineering. The Space runs the Docker image in this repository. Docker Spaces are an optional paid host. The free public demo is the Render web service described in the GitHub README.

Set these Space secrets (Settings → Variables and secrets), never in the image:

- `GROQ_API_KEY` — free Groq key, used by the default preset
- `SECRET_KEY` — long random string
- `ADMIN_EMAIL` and `ADMIN_PASSWORD` — bootstrap administrator
- `DATABASE_URL` — optional Neon or Supabase Postgres, so users survive a restart
- `DEMO_MODE` — leave the image default `true` on a public Space

The container listens on `$PORT` when it is set, and on port 7860 otherwise (`app_port` above). The disk on a Space is ephemeral. Without `DATABASE_URL`, accounts and uploads disappear when the Space restarts. The demo corpus is re-ingested on startup.
