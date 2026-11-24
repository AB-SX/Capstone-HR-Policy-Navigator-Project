# Runbook: deploy HR Policy Navigator to AWS (EC2, Sydney)

Target: one free-tier-eligible EC2 instance in `ap-southeast-2` running two containers with `docker compose`: the app (Streamlit + agents + local retrieval models) and Caddy (HTTPS in front of it). Decision: ADR-007. Site: `https://54-79-216-68.sslip.io` (Elastic IP 54.79.216.68). Time: about 45 minutes, most of it the first image build.

The server builds from **our own GitHub repo** (`Shubhi87/Capstone-HR-Policy-Navigator-Project`, branch `feature/rag-agents-eval`) using a read-only deploy key. Switching to the team repo later is in section 8.

## 0. Laptop: make sure GitHub has everything the server needs

```powershell
cd "C:\Shubhi\AI&ML Course\capstone\Capstone-HR-Policy-Navigator-Project"
git status --short
git ls-files data/index certs
git log origin/feature/rag-agents-eval --oneline -1
```

| Command | What it does |
|---|---|
| `git status --short` | Lists changes not yet committed. Empty = everything is committed. |
| `git ls-files data/index certs` | Shows that the search index (`chunks.jsonl`, `vectors.npy`, `manifest.json`) and the endpoint certificate are in git. The server only gets what is in git. |
| `git log origin/... -1` | Shows the latest commit GitHub has. It should match your latest local commit. |

If something is missing: `git add -A; git commit -m "..."; git push`.

## 1. AWS console: create the server

Region **Asia Pacific (Sydney) ap-southeast-2** (top right). **EC2 → Launch instance**:

| Setting | Value | Why |
|---|---|---|
| Name | `hrnav` | Label only. |
| AMI | Ubuntu Server 24.04 LTS | Standard Linux the commands below assume. |
| Instance type | `m7i-flex.large` (8 GB) if marked *Free tier eligible*, else `c7i-flex.large` (4 GB) | The app needs about 2–3 GB RAM for the embedding and reranker models. |
| Key pair | Create new → `hrnav-key`, type RSA, format `.pem` | The private key you log in with. The browser downloads it once; keep it safe. |
| Network | Allow SSH from **My IP**; allow HTTP and HTTPS from the internet | 22 = your terminal only; 80/443 = the website for everyone. |
| Storage | 30 GB gp3 | Docker image (~4 GB) plus build cache and logs. |
| Advanced details → User data | script below | Runs once at first boot. |

```bash
#!/bin/bash
apt-get update -y && apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

| Line | What it does |
|---|---|
| `apt-get ... git` | Updates the package list and installs curl and git. |
| `get.docker.com` | Docker's official installer: Docker Engine and the `docker compose` plugin. |
| `usermod -aG docker ubuntu` | Lets the `ubuntu` user run Docker without `sudo`. |
| `fallocate ... swapon` | Creates 4 GB of swap (disk used as spare memory) so the build doesn't run out of RAM on a 4 GB machine. |
| `echo ... /etc/fstab` | Keeps the swap after a reboot. |

Then:
- **Elastic IPs → 54.79.216.68 → Actions → Associate** → choose the instance. A fixed public IP, so the site address never changes.
- **Billing → Budgets → Create → Monthly cost budget $10**, email alert at 80%. A safety net in case anything stops being free.

Already have a running instance launched **without** the user-data script? Run the same lines after connecting (step 2), each with `sudo`, then `exit` and reconnect.

## 2. Laptop: connect to the server

```powershell
mkdir $HOME\.ssh -Force
Move-Item $HOME\Downloads\hrnav-key.pem $HOME\.ssh\
icacls $HOME\.ssh\hrnav-key.pem /inheritance:r /grant:r "$($env:USERNAME):(R)"
ssh -i $HOME\.ssh\hrnav-key.pem ubuntu@54.79.216.68
```

| Command | What it does |
|---|---|
| `mkdir` / `Move-Item` | Keeps the key in your user `.ssh` folder, **outside the project**, so it can never be pushed to git. |
| `icacls ... /inheritance:r /grant:r` | Makes the key readable only by you. SSH refuses keys other users can read ("UNPROTECTED PRIVATE KEY FILE"). |
| `ssh -i key ubuntu@IP` | Opens a terminal on the server as user `ubuntu`. Type `yes` to the fingerprint question the first time. |

On the server:

```bash
docker --version && docker compose version && free -h
```

Checks Docker and Compose are installed and shows memory plus ~4 GB swap. "docker: not found" = the boot script is still running: wait 2 minutes, `exit`, reconnect.

## 3. Server: get the code (read-only deploy key)

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/hrnav_deploy && cat ~/.ssh/hrnav_deploy.pub
```

Creates a key pair on the server just for reading the repo and prints the **public** half. The private half never leaves the server.

GitHub → **your repo → Settings → Deploy keys → Add deploy key**: title `aws-hrnav`, paste the line, leave **Allow write access off**. The server can now read this one repo and nothing else, and cannot push.

```bash
printf 'Host github.com\n  IdentityFile ~/.ssh/hrnav_deploy\n  StrictHostKeyChecking accept-new\n' >> ~/.ssh/config
git clone git@github.com:Shubhi87/Capstone-HR-Policy-Navigator-Project.git hrnav
cd hrnav && git checkout feature/rag-agents-eval && git log --oneline -1 && ls data/index/c3
```

| Command | What it does |
|---|---|
| `printf ... >> ~/.ssh/config` | Tells SSH to use the deploy key for github.com and to trust GitHub's host key on first contact. |
| `git clone ...` | Downloads the repo into `~/hrnav`. |
| `git checkout feature/rag-agents-eval` | Switches to the branch with the app. |
| `git log -1` / `ls data/index/c3` | Confirms the latest commit and that the search index arrived. |

## 4. Secrets and the endpoint check

Laptop, **second PowerShell window**, in the project folder:

```powershell
scp -i $HOME\.ssh\hrnav-key.pem .env ubuntu@54.79.216.68:~/hrnav/.env
```

`scp` copies your local `.env` (API keys) to the server over the same SSH connection. Secrets never go through git.

Server (replace the three `<...>` values with codes you choose):

```bash
cd ~/hrnav
sed -i 's/\r$//' .env
sed -i '/^HRNAV_ACCESS_CODE=/d;/^HRNAV_ADMIN_CODE=/d;/^HRNAV_HR_CODE=/d;/^HRNAV_DEV_MODE=/d;/^SITE_ADDRESS=/d;/^COURSE_CA_CERT=/d;/^HRNAV_API__RATE_LIMIT_PER_MINUTE=/d' .env
cat >> .env <<'EOF'
COURSE_CA_CERT=certs/vm04-ca.crt
SITE_ADDRESS=54-79-216-68.sslip.io
HRNAV_ACCESS_CODE=<code for the team>
HRNAV_ADMIN_CODE=<different code for /?admin=1>
HRNAV_HR_CODE=<code for HR reviewers at /?hr=1>
HRNAV_API__RATE_LIMIT_PER_MINUTE=30
LANGSMITH_PROJECT_PROD=hrnav-prod
EOF
chmod 600 .env
set -a; . ./.env; set +a
curl -s -o /dev/null -w "qwen: %{http_code}\n" --cacert certs/vm04-ca.crt -H "Authorization: Bearer $QWEN_API_KEY" "$QWEN_BASE_URL/models"
```

| Command | What it does |
|---|---|
| `sed -i 's/\r$//'` | Removes Windows line endings; otherwise every value ends in an invisible character and keys fail. |
| `sed -i '/^NAME=/d'` | Deletes laptop-only settings so they aren't duplicated (e.g. developer mode stays off in production). |
| `cat >> .env <<'EOF'` | Appends the production settings: certificate path inside the container, site name, the three access codes, 30 questions/minute per user (team testers may share one office IP), LangSmith project for production traces. |
| `chmod 600 .env` | Only the `ubuntu` user can read the secrets file. |
| `set -a; . ./.env; set +a` | Loads the `.env` values into this terminal session for the test. |
| `curl ... /models` | Calls the Qwen endpoint from AWS and prints only the HTTP status (never the key). **200** = reachable. **000** or a timeout = the endpoint doesn't accept traffic from AWS: stop and sort this out before building. |

`SITE_ADDRESS` uses **sslip.io**, a public DNS service where `54-79-216-68.sslip.io` always resolves to `54.79.216.68`. That gives a real hostname, so Caddy can get a free Let's Encrypt HTTPS certificate without buying a domain.

## 5. Build and start

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs caddy | grep -i "certificate obtained"
```

| Command | What it does |
|---|---|
| `docker compose build` | Builds the app image from the `Dockerfile`: Python 3.12, CPU-only PyTorch, the requirements, downloads and bakes in the embedding model and reranker (no downloads at start-up), copies code, config, certificate, index and processed handbook, and runs as a non-root user. About 10–15 minutes the first time, faster later (cached layers). |
| `docker compose up -d` | Starts both containers in the background (`-d`). `app` listens only inside Docker; `caddy` takes ports 80/443 and forwards to the app. Both restart automatically after a crash or reboot. |
| `docker compose ps` | Shows container status. `app` becomes **healthy** once the health check (`/_stcore/health`) answers, usually within a minute. |
| `docker compose logs caddy \| grep ...` | Confirms Caddy got the HTTPS certificate. If it's not there yet, wait a minute: Let's Encrypt has to reach the server on port 80 first. |

Useful while checking: `docker compose logs -f app` (live app log, Ctrl+C to stop following), `free -h`, `df -h`.

## 6. Test from outside

Use a phone on mobile data (proves it works from outside your network):

| URL | Who | Check |
|---|---|---|
| `https://54-79-216-68.sslip.io` | team and testers (access code) | Padlock, topic cards, an answer with Sources |
| `https://54-79-216-68.sslip.io/?admin=1` | you (admin code) | Usage numbers move after a question; HR requests list |
| `https://54-79-216-68.sslip.io/?hr=1` | HR reviewer (HR code) | Change a request's status; the employee sees it under "Check a request" |

Checks to record for the report:

| Check | How | Expected |
|---|---|---|
| HTTPS | phone on mobile data | padlock, app loads |
| Answer with sources | pick a topic, then a guide question | cited answer, Sources panel |
| Request boundary | "Please raise an HR ticket…" → Cancel, then again → edit → Submit | nothing filed on Cancel; one request on Submit, visible at `?admin=1` |
| Restart keeps the conversation | `docker compose restart app`, then a follow-up in the same chat | follow-up still has context |
| Rate limit | more than 30 questions in a minute from one network | told to wait |
| Traces | LangSmith project `hrnav-prod` | one trace per question |
| Usage log has no question text | `docker compose exec app tail -3 /app/runtime/app_log.jsonl` | status, latency, model calls only |

## 7. Update, stop, tear down

```bash
cd ~/hrnav && git pull && docker compose build && docker compose up -d   # deploy a new commit (about 1 minute downtime)
docker compose down                                                      # stop; data volumes are kept
```

`git pull` fetches the latest pushed commit; `build` rebuilds only changed layers; `up -d` replaces the running container. Requests, feedback and logs live in the `runtime` Docker volume, so they survive updates.

After the demo week (about Fri 4 Dec): **terminate the instance**, **release the Elastic IP** (AWS charges for an unattached one), delete the deploy key on GitHub, and delete the key pair in EC2.

## 8. Later: build from the team repo instead

Deploy keys can only be added by a repo admin, and one key works for one repo. When the team repo has our changes merged:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/hrnav_deploy_team && cat ~/.ssh/hrnav_deploy_team.pub   # repo owner adds this as a read-only deploy key
cat >> ~/.ssh/config <<'EOF'
Host github-team
  HostName github.com
  IdentityFile ~/.ssh/hrnav_deploy_team
EOF
cd ~/hrnav && git remote set-url origin git@github-team:<owner>/<repo>.git
git fetch origin && git checkout main && git pull && docker compose build && docker compose up -d
```

`.env`, requests and logs stay on the server and are untouched. Then remove the old deploy key from our repo.
