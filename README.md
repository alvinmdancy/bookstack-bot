# bookstack-bot

A Discord bot that connects to your [BookStack](https://www.bookstackapp.com/) wiki. Use slash commands in Discord to search pages, look up content, create stubs, and browse your books and shelves.

Built with Python, discord.py, Docker, and Kubernetes.

---

## Commands

| Command | Description |
|---|---|
| `/wiki search <query>` | Search all BookStack content |
| `/wiki page <id>` | Get a page by ID |
| `/wiki create <book_id> <title> [content]` | Create a page stub in a book |
| `/wiki list books` | List all books |
| `/wiki list shelves` | List all shelves |

### Examples

**Search for content:**
```
/wiki search docker networking
```
Returns up to 5 results across pages, chapters, and books with a preview and a link to each.

**Get a specific page:**
```
/wiki page 42
```
Returns the page title, content preview, book slug, and a link to open it in BookStack.

**Create a page stub:**
```
/wiki create 3 "Kubernetes Cheatsheet"
```
Creates a blank page titled "Kubernetes Cheatsheet" inside book ID 3. You can pass optional markdown content as a third argument.

**List your books:**
```
/wiki list books
```
Returns a list of all books with their IDs — useful for finding the book ID before running `/wiki create`.

**List your shelves:**
```
/wiki list shelves
```
Returns all shelves with their IDs.

---

## Requirements

- Docker and Docker Compose
- A running BookStack instance
- A Discord application and bot token

---

## Setup

### 1. Discord application

1. Go to https://discord.com/developers/applications → New Application
2. Bot tab → Reset Token → copy the token
3. OAuth2 → URL Generator → scopes: `bot` + `applications.commands`
4. Bot permissions: `Send Messages`, `Embed Links`
5. Open the generated URL and invite the bot to your server

To find your Guild ID: Discord Settings → Advanced → Enable Developer Mode → right-click your server → Copy Server ID.

### 2. BookStack API token

Profile menu → Edit Profile → API Tokens → Create Token → copy the ID and secret. BookStack only shows the secret once.

### 3. Environment

```bash
cp .env.example .env
```

Fill in all values:

```
DISCORD_TOKEN=your-bot-token
DISCORD_GUILD_ID=your-guild-id
BOOKSTACK_URL=http://your-bookstack-host
BOOKSTACK_TOKEN_ID=your-token-id
BOOKSTACK_TOKEN_SECRET=your-token-secret
```

`DISCORD_GUILD_ID` scopes slash commands to one server and syncs them instantly. Leave it blank for global deployment — global sync takes up to an hour.

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
│   ├── main.py                  # Entry point, slash command sync
│   ├── bookstack/client.py      # Async BookStack API client
│   ├── cogs/wiki.py             # Slash command definitions
│   └── utils/formatting.py      # Discord embed builders, HTML stripping
├── k8s/
│   ├── base/                    # Shared Kubernetes manifests
│   └── overlays/
│       ├── local/               # k3s overlay
│       └── eks/                 # AWS EKS overlay (image path patch)
├── .github/workflows/ci.yml     # Lint and Docker build on push
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Notes

- The bot runs as a single replica. Discord's Gateway allows one active WebSocket session per token — multiple replicas cause reconnect loops.
- BookStack returns HTML for page content. The bot strips tags and decodes entities before sending text to Discord.
- `k8s/base/secret.yaml` is gitignored. Never commit real credentials.