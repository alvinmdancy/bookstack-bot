# bookstack-bot

A Discord bot that connects to your [BookStack](https://www.bookstackapp.com/) wiki. Use a single slash command to browse your shelves and books, then export any book as a PDF with working Mermaid diagrams, or jump straight to it in your browser.

Built with Python, discord.py, aiohttp, Gotenberg, Docker, and Kubernetes.

---

## Commands

| Command | Description |
|---|---|
| `/bookstack` | Opens an interactive menu: browse shelves → pick a book → export as PDF or open in browser |

### How it works

Running `/bookstack` opens an ephemeral menu with two options:

- **Browse Shelves** — pick a shelf, then a book from that shelf. Once a book is selected, you get two buttons:
  - **Export PDF** — renders the book (including any Mermaid diagrams) and sends it back as a file
  - **Open in Browser** — a direct link to the book on your BookStack instance
- **Search (basic)** — currently just a placeholder pointing you to search directly in BookStack. Not yet wired up as a real command.

`BookStackClient` also has `search`, `get_page`, and `create_page` methods available for future slash commands, but they aren't currently exposed in the menu.

---

## PDF export: how it actually renders diagrams

BookStack's built-in PDF export uses `dompdf`, which never executes JavaScript. If you have Mermaid diagrams on your pages (via the community Mermaid Viewer hack), they render fine in the browser but show up as raw code blocks in a normal BookStack PDF export.

This bot sidesteps that by rendering pages through [Gotenberg](https://gotenberg.dev/), a Dockerized PDF service built on headless Chromium. Since Chromium actually runs the page's JavaScript before printing, Mermaid diagrams render correctly. The bot fetches the book's page list from BookStack's API, renders each live page through Gotenberg, and merges the results into a single PDF with `pypdf`.

If your BookStack instance sits behind Cloudflare Access, or has private content, there are two extra authentication steps involved — covered below.

---

## Requirements

- Docker and Docker Compose
- A running BookStack instance
- A running Gotenberg instance (same host or reachable over the network)
- A Discord application and bot token
- If BookStack is behind Cloudflare Access: a Cloudflare Access Service Token
- If the content you want to export is private (not public): a dedicated BookStack service account

---

## Setup

### 1. Discord application

1. Go to https://discord.com/developers/applications → New Application
2. Bot tab → Reset Token → copy the token
3. OAuth2 → URL Generator → scopes: `bot` + `applications.commands`
4. Bot permissions: `Send Messages`, `Embed Links`, `Read Message History`
5. Open the generated URL and invite the bot to your server

To find your Guild ID: Discord Settings → Advanced → Enable Developer Mode → right-click your server → Copy Server ID.

### 2. BookStack API token

Profile menu → Edit Profile → API Tokens → Create Token → copy the ID and secret. BookStack only shows the secret once.

### 3. Gotenberg

Add Gotenberg alongside your BookStack stack (or anywhere reachable from the bot's container):

```yaml
  gotenberg:
    image: gotenberg/gotenberg:8
    container_name: gotenberg
    restart: unless-stopped
    ports:
      - "3000:3000"
    command:
      - "gotenberg"
      - "--chromium-disable-javascript=false"
      - "--api-timeout=60s"
```

If Gotenberg and the bot run in separate Docker Compose projects (separate networks), point `GOTENBERG_URL` at the host's LAN IP rather than the container name — Compose projects don't share networks by default.

### 4. Cloudflare Access (only if BookStack is behind it)

If your BookStack domain is protected by Cloudflare Access, Gotenberg's headless Chromium has no browser session and will hit Cloudflare's login page instead of real content — for the page itself and every asset (CSS/JS) it loads.

1. Cloudflare Zero Trust dashboard → **Access** → **Service Auth** → **Service Tokens** → create one (e.g. `gotenberg-bookstack-export`)
2. Find the Access application covering your BookStack **domain root** (not a narrower `/api/*` application, if you have one) → **Policies** → add a policy: **Include → Service Auth →** select the token
3. Copy the generated Client ID and Client Secret into `.env` (below)

### 5. BookStack service account (only if the content is private)

If the book/shelf you want to export isn't set to Public inside BookStack's own permissions, Chromium also needs a real BookStack login session — the Cloudflare Access token above only gets it past Cloudflare's edge, not past BookStack's own permission system.

1. In BookStack: **Settings → Users → Invite/Add User**
2. Create a dedicated, low-privilege account (view access only to what you want exportable) — don't reuse your own admin login
3. Add its email/password to `.env` (below)

The bot logs in as this account once per export, captures the session cookie, and hands it to Gotenberg alongside the Cloudflare headers.

### 6. Environment

```bash
cp .env.example .env
```

Fill in:

```
DISCORD_TOKEN=your-bot-token
DISCORD_GUILD_ID=your-guild-id
ALLOWED_CHANNEL_ID=123456789,987654321

BOOKSTACK_URL=https://your-bookstack-domain
BOOKSTACK_TOKEN_ID=your-token-id
BOOKSTACK_TOKEN_SECRET=your-token-secret

GOTENBERG_URL=http://192.168.x.x:3000

# Only needed if BookStack is behind Cloudflare Access:
CF_ACCESS_CLIENT_ID=your-service-token-client-id
CF_ACCESS_CLIENT_SECRET=your-service-token-client-secret

# Only needed if the content you're exporting is private:
BOOKSTACK_SERVICE_EMAIL=export-bot@yourdomain.com
BOOKSTACK_SERVICE_PASSWORD=a-strong-password
```

`DISCORD_GUILD_ID` scopes slash commands to one server and syncs them instantly. Leave it blank for global deployment — global sync takes up to an hour.

`ALLOWED_CHANNEL_ID` is a comma-separated list of channel IDs where bot commands and auto-link detection are allowed.

**One-time cleanup flag:** if you ever end up with stale slash commands stuck in Discord (e.g. leftover from an earlier version of the bot), set `CLEAR_GLOBAL_COMMANDS=true` in `.env` for a single deploy, confirm the logs show `Discord global commands: []`, then set it back to `false` (or remove it) and redeploy. Leaving it `true` permanently causes unnecessary syncing on every restart.

---

## Running

### Docker Compose

```bash
docker compose up --build -d
docker compose logs -f
```

### Python (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

---

## Kubernetes (k3s)

```bash
# Build the image
docker build -t bookstack-bot:local .

# Import it into k3s (k3s does not share Docker's image cache)
docker save bookstack-bot:local | sudo k3s ctr images import -

# Create your secret file
cp k8s/base/secret.example.yaml k8s/base/secret.yaml
# Fill in real values — this file is gitignored

# Deploy
kubectl apply -k k8s/overlays/local/

# Check status
kubectl get pods
kubectl logs -f deployment/bookstack-bot
```

---

## Project structure

```
bookstack-bot/
├── bot/
│   ├── main.py                       # Entry point, slash command sync
│   ├── bookstack/
│   │   ├── client.py                 # Async BookStack API client
│   │   └── gotenberg_export.py       # Renders books via Gotenberg (Mermaid-safe PDF export)
│   ├── cogs/wiki.py                  # /bookstack command + interactive menu views
│   └── utils/formatting.py           # Discord embed builders, HTML stripping
├── k8s/
│   ├── base/                         # Shared Kubernetes manifests
│   └── overlays/
│       ├── local/                    # k3s overlay
│       └── eks/                      # AWS EKS overlay (image path patch)
├── .github/workflows/ci.yml          # Lint and Docker build on push
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Notes

- The bot runs as a single replica. Discord's Gateway allows one active WebSocket session per token — multiple replicas cause reconnect loops.
- BookStack returns HTML for page content. The bot strips tags and decodes entities before sending text to Discord.
- `k8s/base/secret.yaml` is gitignored. Never commit real credentials.
- Book exports render pages sequentially through Gotenberg to avoid overloading a small homelab host. If Gotenberg has headroom, this can be changed to render concurrently.
- If Mermaid diagrams occasionally don't appear in an export, increase `RENDER_DELAY_SECONDS` in `gotenberg_export.py` — it controls how long Chromium waits after page load before printing, to give the diagram's JS time to finish rendering.
- If exports start showing a login page again after this all works, check two separate things: Cloudflare Access (Service Token/policy) and BookStack's own permissions (Public vs. Private) — they're independent layers and either one can block Chromium on its own.
