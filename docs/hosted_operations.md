# Hosted GergVault Operations

This runbook is for the hosted beta at `gergvault.halobridge.ai`.

## Health Check

Run inside the web container:

```bash
python manage.py gergvault_ops_check
```

The command verifies:

- `DEBUG` is off
- secure session and CSRF cookies are enabled
- HSTS is enabled
- traffic tracking is enabled
- rate limiting is enabled
- tenants exist
- database access works

## Backup Baseline

Hosted GergVault stores user-visible state in Postgres and uploaded media files.

Minimum backup set:

- Postgres database volume
- uploaded media directory
- production `.env` stored in a secret manager or private ops vault

For this Docker-hosted beta, schedule:

```bash
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > gergvault-$(date +%F).sql
tar -czf gergvault-media-$(date +%F).tgz backend/media
```

Move backups off-host after creation.

## Monitoring Baseline

At minimum monitor:

- homepage HTTPS 200
- signup HTTPS 200
- `/card-vault/` anonymous 302 to login
- web container running
- Postgres container healthy
- `python manage.py gergvault_ops_check`

Alert on:

- failed HTTPS checks
- repeated 5xx responses
- web container restart loop
- Postgres unhealthy
- high signup/login 429 volume

## Media Privacy

The app should render uploaded images through authenticated URLs under:

```text
/card-vault/media/<image_id>/
```

Direct public `/media/` serving should be disabled for the hosted deployment once protected image URLs are in use.
