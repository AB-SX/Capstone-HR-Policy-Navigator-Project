# Runbook: deploy HR Policy Navigator to AWS (EC2, Sydney)

Target: one free-tier-eligible instance (`m7i-flex.large`, or `c7i-flex.large` with swap) in `ap-southeast-2` running `docker compose` (app + Caddy). Decision: ADR-007. Time: about 45 minutes, most of it the first image build.

## 0. Before you start (laptop)

- The branch you deploy is pushed to GitHub and includes `data/index/c3/` (chunks, vectors, manifest), `data/processed/`, `certs/vm04-ca.crt`, `Dockerfile`, `docker-compose.yml`, `deploy/Caddyfile`, `.streamlit/config.toml`.
- Your local `.env` works (smoke test passes).
- The app runs locally: `streamlit run src/app/navigator.py` (only when no evaluation is running; the endpoint takes one request at a time).

## 1. Launch the instance (AWS console, region Sydney)

| Setting | Value |
|---|---|
| AMI | Ubuntu Server 24.04 LTS |
| Type | `m7i-flex.large` (8 GB) if listed as **Free tier eligible**; else `c7i-flex.large` (4 GB) plus the swap step below |
| Key pair | new, `.pem`, keep it safe |
| Storage | 30 GB gp3 |
| Security group | SSH 22 from **My IP**; HTTP 80 and HTTPS 443 from `0.0.0.0/0` |
| User data | the Docker install script below |

```bash
#!/bin/bash
apt-get update -y && apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu
# 4 GB swap (needed on c7i-flex.large, harmless on 8 GB types)
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Then **Elastic IPs → Allocate → Associate** with the instance. Your site name is the IP with dashes plus `.sslip.io`, for example `13.54.12.34` → `13-54-12-34.sslip.io`.

Set a budget: **Billing → Budgets → Create → Monthly cost budget, $10**, email alert at 80%.

## 2. Connect (PowerShell on the laptop)

```powershell
icacls .\hrnav-key.pem /inheritance:r /grant:r "$($env:USERNAME):(R)"
ssh -i .\hrnav-key.pem ubuntu@<ELASTIC_IP>
docker --version          # if "not found", wait a minute: user data is still running
```

## 3. Get the code onto the server (read-only deploy key)

On the server:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/hrnav_deploy
cat ~/.ssh/hrnav_deploy.pub
```

On GitHub: repo → **Settings → Deploy keys → Add deploy key**, paste it, leave "Allow write access" off. Back on the server:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/hrnav_deploy
EOF
git clone git@github.com:Shubhi87/Capstone-HR-Policy-Navigator-Project.git hrnav
cd hrnav && git checkout feature/rag-agents-eval     # or main once merged
```

## 4. Secrets

From the laptop, in the project folder:

```powershell
scp -i .\hrnav-key.pem .env ubuntu@<ELASTIC_IP>:~/hrnav/.env
```

On the server:

```bash
cd ~/hrnav
sed -i 's/\r$//' .env                    # Windows line endings break env values
sed -i '/^HRNAV_ACCESS_CODE=/d;/^SITE_ADDRESS=/d;/^COURSE_CA_CERT=/d' .env
echo 'COURSE_CA_CERT=certs/vm04-ca.crt' >> .env
cat >> .env <<'EOF'
SITE_ADDRESS=13-54-12-34.sslip.io
HRNAV_ACCESS_CODE=<pick a code to share with reviewers>
LANGSMITH_PROJECT_PROD=hrnav-prod
EOF
chmod 600 .env
```

## 5. Build and start

```bash
docker compose build              # first time about 10 minutes (torch CPU + models)
docker compose up -d
docker compose ps                 # app should become "healthy" within about a minute
docker compose logs -f caddy      # look for "certificate obtained successfully"
```

Open `https://<site-address>` from your phone on mobile data, enter the access code, ask a starter question.

## 6. Checks to record for the report

| Check | How | Expected |
|---|---|---|
| HTTPS works | phone on mobile data | padlock, app loads |
| Answer with sources | starter question | cited answer, Sources panel |
| Ticket boundary | "Please raise an HR ticket…" → Cancel, then again → Confirm | nothing filed on Cancel, one line in `runtime/tickets.jsonl` on Confirm |
| Restart keeps the conversation | `docker compose restart app`, then a follow-up in the same chat | follow-up still has context (M2) |
| Rate limit | 11 quick questions | the 11th is told to wait |
| Traces | LangSmith project `hrnav-prod` | one trace per question |
| Usage log | `docker compose exec app tail -5 /app/runtime/app_log.jsonl` | status, latency, model calls; no question text |

## 7. Update, stop, tear down

```bash
git pull && docker compose build && docker compose up -d     # deploy a change
docker compose down                                          # stop (volumes kept)
```

After about Fri 4 Dec: terminate the instance, **release the Elastic IP** (it costs money while unattached), delete the deploy key on GitHub.
