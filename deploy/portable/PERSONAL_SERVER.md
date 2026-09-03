# Clean production bootstrap on a personal server

This runbook is for the current recovery decision: the old Railway production state is unrecoverable, so the personal server starts from an empty PostgreSQL database and a new object store. Do **not** run demo/staging seed scripts.

The application release below is the immutable candidate that passed staging run `33714503493`; all mandatory supported staging certification gates passed and the decision was `READY FOR UAT`:

- Git SHA: `ad44e5d36dc00e75e8d06884ea70e8d37ca27e8b`
- release build run: `33714417570`
- API: `sha256:e97288e821a6bedfb28872f2af92523fef74a919ee20af0ad40fb23a5a37190e`
- worker: `sha256:24285be8126db5c7e99760efff97229c03e1be8fc3884926cc82c7ce9d4a04ae`
- web: `sha256:2515e06268168ba2296d146210e4bd6ce372cdaab6df950d93882cc28698d7b3`

The portable deployment tooling can live on a newer Git commit; do not rebuild the certified application images just because the runbook changes.

## 1. Server prerequisites

The currently certified images were built on GitHub's Linux/amd64 runners. Use an `x86_64`/`amd64` Linux host for this first production deployment. If the personal server is ARM64, stop and certify a multi-architecture release instead of rebuilding ad hoc.

Recommended for the all-in-one stack:

- 4 CPU cores;
- 8 GiB RAM;
- 30+ GiB free disk before application data/backups;
- a stable public IP or router/NAT forwarding for TCP 80 and 443;
- Docker Engine + Docker Compose v2;
- Git, curl and Python 3.

If the server is behind CGNAT and cannot receive inbound 80/443 from the public Internet, the bundled Caddy TLS path will not work directly. Use a public reverse tunnel/ingress or another server with public reachability.

Clone the deployment source:

```bash
sudo mkdir -p /opt/catora
sudo chown "$USER":"$USER" /opt/catora
git clone https://github.com/waseem99/Catora.git /opt/catora/repo
cd /opt/catora/repo
git checkout main
git pull --ff-only
```

Run the non-secret preflight:

```bash
bash deploy/portable/preflight-personal-server.sh
```

Do not continue while it reports failures.

## 2. Create production secrets locally

Generate a protected environment file on the server. The helper does not print generated secrets and refuses to overwrite an existing production file:

```bash
bash deploy/portable/prepare-personal-server-env.sh
```

The resulting file is:

```text
deploy/portable/.env.production
```

Keep it mode `0600`, never commit it, and make an encrypted/off-machine backup. It contains the new authentication pepper, database password, MinIO credentials and Service Visibility encryption key for this clean production state.

The clean personal-server template deliberately enables:

- Service Visibility;
- approved WordPress drafts;
- recurring Service Visibility monitoring;
- measurement connector UI/sync support.

Unrelated connectors remain disabled until their real production credentials are deliberately configured.

## 3. Pull the exact certified application images

The GHCR images may require GitHub Package authentication depending on package visibility. First try the normal pull below. If GHCR returns `denied`, authenticate with a token that has only the required package-read permission; never paste that token into chat or a committed file.

Validate Compose and pull exact digests:

```bash
docker compose --env-file deploy/portable/.env.production \
  -f deploy/portable/docker-compose.production.yml \
  -f deploy/portable/docker-compose.dependencies.yml \
  -f deploy/portable/docker-compose.edge.yml \
  config
docker compose --env-file deploy/portable/.env.production \
  -f deploy/portable/docker-compose.production.yml \
  -f deploy/portable/docker-compose.dependencies.yml \
  pull api worker web postgres redis minio
```

If package authentication is required, use a local shell prompt so the token is not stored in shell history:

```bash
read -r -s -p "GitHub package token: " GHCR_TOKEN; printf '\n'
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u waseem99 --password-stdin
unset GHCR_TOKEN
```

Then repeat the pull.

## 4. Start dependencies and initialize storage

```bash
docker compose --env-file deploy/portable/.env.production \
  -f deploy/portable/docker-compose.production.yml \
  -f deploy/portable/docker-compose.dependencies.yml \
  up -d postgres redis minio
docker compose --env-file deploy/portable/.env.production \
  -f deploy/portable/docker-compose.production.yml \
  -f deploy/portable/docker-compose.dependencies.yml \
  --profile ops run --rm storage-init
```

Because this is a clean bootstrap, there is no Railway database/object-store restore step.

## 5. Run the schema migration exactly once

```bash
docker compose --env-file deploy/portable/.env.production \
  -f deploy/portable/docker-compose.production.yml \
  -f deploy/portable/docker-compose.dependencies.yml \
  --profile ops run --rm migrate
```

The worker must never own migrations.

## 6. Start API, worker and web

```bash
docker compose --env-file deploy/portable/.env.production \
  -f deploy/portable/docker-compose.production.yml \
  -f deploy/portable/docker-compose.dependencies.yml \
  up -d api worker web
```

Check locally before exposing DNS:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health/live
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready
curl --fail --silent --show-error http://127.0.0.1:8000/health/release
curl --fail --silent --show-error http://127.0.0.1:3000/api/release
curl --fail --silent --show-error http://127.0.0.1:3000/login >/dev/null
```

`/health/ready` must report PostgreSQL, Redis and object storage ready before continuing.

## 7. Bootstrap the first production owner

Do not use any demo or staging seed script. Create the first organization/workspace/owner through Catora's real one-time `/api/v1/auth/bootstrap` flow:

```bash
bash deploy/portable/bootstrap-owner.sh
```

The helper prompts for the owner email/password without printing the password. The password must be at least 12 characters.

Bootstrap is a first-install operation. Do not repeatedly run it after the production owner exists.

## 8. Point DNS and enable HTTPS

Create/update public DNS records so both names resolve to this server's public ingress:

```text
catora.codistan.org
api.catora.codistan.org
```

Ensure inbound TCP 80/443 reaches this host. UDP 443 is optional but enables HTTP/3.

Then start the Caddy edge overlay:

```bash
docker compose --env-file deploy/portable/.env.production \
  -f deploy/portable/docker-compose.production.yml \
  -f deploy/portable/docker-compose.dependencies.yml \
  -f deploy/portable/docker-compose.edge.yml \
  up -d caddy
```

Caddy automatically obtains/renews TLS certificates after the DNS records and inbound ports are correct.

Verify canonical production URLs:

```bash
curl --fail --silent --show-error https://api.catora.codistan.org/health/live
curl --fail --silent --show-error https://api.catora.codistan.org/health/ready
curl --fail --silent --show-error https://api.catora.codistan.org/health/release
curl --fail --silent --show-error https://catora.codistan.org/api/release
curl --fail --silent --show-error https://catora.codistan.org/login >/dev/null
```

Then sign in at `https://catora.codistan.org` with the newly bootstrapped owner.

## 9. First production acceptance

Before reconnecting Hilarious, confirm:

- API live/ready are green;
- API, worker and web expose the certified SHA/digests;
- owner login works;
- workspace navigation works;
- a worker-backed catalog operation completes;
- containers restart successfully after a controlled `docker compose restart`;
- the populated `.env.production` has an encrypted/off-machine backup;
- PostgreSQL and MinIO have a real backup schedule before production data becomes important.

## 10. Reconnect Hilarious as new production state

The old Railway database is gone. The historic Hilarious Service Visibility source ID is not expected to exist here.

After production acceptance:

1. create a fresh Hilarious Service Visibility source in the new production workspace;
2. install/confirm WordPress plugin `0.2.3`;
3. enter the newly generated bridge credentials in WordPress;
4. require Connection Health = Healthy;
5. run a manual snapshot;
6. prove credential rotation old-fails/new-works;
7. prove publish -> automatic re-scan;
8. approve one remediation and require an unpublished WordPress draft;
9. manually publish and require the automatic verification re-scan;
10. connect exact GSC/GA4 properties using the managed Google service-account environment credential.

The Hilarious loop, not visual polish, is the production-success criterion.
