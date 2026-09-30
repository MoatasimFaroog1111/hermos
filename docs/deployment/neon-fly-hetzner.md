# Hermes multi-cloud deployment

This repository is prepared for the following production layout:

- **Neon**: managed PostgreSQL / branchable data services.
- **Fly.io**: always-on Hermes runtime in Singapore.
- **Hetzner**: Docker runtime using the same image and persistent `/opt/data` volume.

## Neon

Current project:
- Project ID: `muddy-night-08698347`
- Project name: `guardian-chatgpt-enterprise`
- Production branch: `br-dawn-mountain-b3bptaut`
- Region: `aws-ap-southeast-1`

Neon is not used as a replacement for the Hermes Docker host. Connect only components/plugins that explicitly support PostgreSQL. Keep the connection string in platform secrets as `DATABASE_URL`; never commit it.

## Fly.io

The repository root now contains `fly.toml`.

Recommended region: `sin`, to stay close to the existing Neon Singapore project.

Before the first deploy:

```bash
fly auth login
fly apps create hermos-moatasim
fly volumes create hermes_data --region sin --size 5
fly secrets set \
  HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin \
  HERMES_DASHBOARD_BASIC_AUTH_PASSWORD='<strong-random-password>'
```

Add the existing Hermes/Telegram/model-provider secrets with `fly secrets set` as well. If a component uses Neon, also set:

```bash
fly secrets set DATABASE_URL='<neon-pooled-connection-string>'
```

Deploy:

```bash
fly deploy
fly status
```

The service health endpoint is `/api/status`.

## Hetzner

The repository root now contains `docker-compose.hetzner.yml`.

On a new Ubuntu server:

```bash
apt-get update
apt-get install -y docker.io docker-compose-plugin git
git clone https://github.com/MoatasimFaroog1111/hermos.git
cd hermos
cp .env.example .env
```

Put production secrets in `.env`, including dashboard authentication and existing Hermes provider / Telegram values. If a component uses Neon, add `DATABASE_URL` there.

Start:

```bash
docker compose -f docker-compose.hetzner.yml up -d --build
docker compose -f docker-compose.hetzner.yml ps
curl -fsS http://127.0.0.1:9119/api/status
```

For an Internet-facing dashboard, put port 9119 behind an authenticated TLS reverse proxy and restrict the Hetzner firewall. Do not commit `.env`.

## Persistence

Both Fly and Hetzner persist Hermes state at `/opt/data`. Do not run both installations against the same Telegram bot token in polling mode at the same time. Use one active gateway and one standby, or separate bot identities.
