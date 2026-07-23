SHELL := /bin/bash
.PHONY: setup setup-gui start stop restart logs logs-api logs-ui status caddy-trust update backup-env db-backup db-restore clean help generate-wizard-narration

##@ First-time setup
setup:           ## Run interactive terminal wizard (generates .env, pulls images, starts services)
	@bash setup.sh

setup-gui:       ## Same as setup, but as a form in your browser instead of terminal prompts
	@bash scripts/setup-gui-common.sh

##@ Day-to-day operations
start:           ## Start Bede in the background
	docker compose up -d
	@echo ""
	@echo "Bede is starting — run 'make status' to check readiness."

stop:            ## Stop all services (data stays in your database)
	docker compose down

restart:         ## Restart all services (picks up .env changes)
	docker compose down
	docker compose up -d

logs:            ## Tail logs from all services (Ctrl-C to stop)
	docker compose logs -f

logs-api:        ## Tail API logs only
	docker compose logs -f api

logs-ui:         ## Tail UI logs only
	docker compose logs -f ui

status:          ## Show container health and last 20 API log lines
	@echo "=== Container status ==="
	docker compose ps
	@echo ""
	@echo "=== API health ==="
	@curl -skf https://localhost/api/health 2>/dev/null | python3 -m json.tool || echo "  (not reachable yet — still starting)"
	@echo ""
	@echo "=== Recent API logs ==="
	docker compose logs --tail=20 api

caddy-trust:     ## Export Caddy's root CA cert — install on each LAN tablet once (CLI route; http://<server-ip>/trust is the no-CLI route)
	@docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt > sage-root-ca.crt 2>/dev/null || \
	  { echo "Caddy is not running yet. Start with 'make start' first."; exit 1; }
	@echo ""
	@echo "Saved: sage-root-ca.crt"
	@echo ""
	@echo "No terminal needed instead? Open http://<server-ip>/trust on the tablet"
	@echo "itself (or scan the QR code shown there) and skip everything below."
	@echo ""
	@echo "Install this cert on each tablet by hand:"
	@echo "  iPad/iPhone  : AirDrop the file → Settings → General → VPN & Device Management → trust it"
	@echo "  Android      : Settings → Security → Install a certificate → CA certificate"
	@echo "  Windows      : Double-click → Install Certificate → Trusted Root Certification Authorities"
	@echo "  macOS        : Double-click → Keychain Access → set to Always Trust"
	@echo ""
	@echo "After installing, open https://$$(hostname -I | awk '{print $$1}') on the tablet."
	@echo ""
	@echo "iPad/iPad Pro shortcut: run 'make ipad-profile' for a single-tap install"
	@echo "(cert trust + Home Screen icon in one profile) instead of the manual steps above."

ipad-profile:    ## Generate one .mobileconfig for iPad: CA trust + Home Screen icon in a single install
	@bash ipad-profile.sh

generate-wizard-narration:  ## One-time: generate the setup wizard's spoken narration (needs OPENAI_API_KEY) — commit the result
	@test -n "$$OPENAI_API_KEY" || { echo "Usage: OPENAI_API_KEY=sk-... make generate-wizard-narration"; exit 1; }
	python3 scripts/setup_wizard/generate_narration.py

##@ Maintenance
update:          ## Pull latest images and restart
	git pull
	docker compose pull
	docker compose up -d --build

backup-env:      ## Copy .env to .env.backup (never commit either file)
	cp .env .env.backup
	@echo ".env backed up to .env.backup"

db-backup:       ## Back up the LOCAL Postgres database (only if COMPOSE_PROFILES=local-db) to backups/
	@mkdir -p backups
	@chmod 700 backups
	@F=backups/bede-$$(date -u +%Y%m%d-%H%M%S).sql; \
	docker compose exec -T db pg_dump -U sage bede > $$F; \
	chmod 600 $$F; \
	echo "Saved to $$F (permissions 600 — this is a raw SQL dump, same file-permission bar as .env: most columns are pre-encrypted at the application layer, but the encryption_config table with the KEK-wrapped DATA_KEY is in this file too). Using a MANAGED database instead? Your provider (Neon/Supabase/etc.) handles backups for you."

db-restore:      ## Restore the LOCAL Postgres database from a backup: make db-restore FILE=backups/bede-....sql
	@test -n "$(FILE)" || { echo "Usage: make db-restore FILE=backups/bede-YYYYMMDD-HHMMSS.sql"; exit 1; }
	@test -f "$(FILE)" || { echo "File not found: $(FILE)"; exit 1; }
	@echo "This REPLACES all data currently in the local database. Ctrl-C now to cancel."
	@sleep 5
	docker compose exec -T db psql -U sage -d bede < $(FILE)
	@echo "Restored from $(FILE) — restart the API so it picks up any changed encryption keys: make restart"

clean:           ## Remove stopped containers and dangling images (data stays in database)
	docker compose down --remove-orphans
	docker image prune -f

##@ Help
help:            ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
