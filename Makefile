SHELL := /bin/bash
.PHONY: setup start stop restart logs logs-api logs-ui status caddy-trust update backup-env clean help

##@ First-time setup
setup:           ## Run interactive first-run wizard (generates .env, pulls images, starts services)
	@bash setup.sh

##@ Day-to-day operations
start:           ## Start Sage in the background
	docker compose up -d
	@echo ""
	@echo "Sage is starting — run 'make status' to check readiness."

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

caddy-trust:     ## Export Caddy's root CA cert — install on each LAN tablet once
	@docker compose exec caddy cat /data/pki/authorities/local/root.crt > sage-root-ca.crt 2>/dev/null || \
	  { echo "Caddy is not running yet. Start with 'make start' first."; exit 1; }
	@echo ""
	@echo "Saved: sage-root-ca.crt"
	@echo ""
	@echo "Install this cert on each tablet:"
	@echo "  iPad/iPhone  : AirDrop the file → Settings → General → VPN & Device Management → trust it"
	@echo "  Android      : Settings → Security → Install a certificate → CA certificate"
	@echo "  Windows      : Double-click → Install Certificate → Trusted Root Certification Authorities"
	@echo "  macOS        : Double-click → Keychain Access → set to Always Trust"
	@echo ""
	@echo "After installing, open https://$$(hostname -I | awk '{print $$1}') on the tablet."

##@ Maintenance
update:          ## Pull latest images and restart
	git pull
	docker compose pull
	docker compose up -d --build

backup-env:      ## Copy .env to .env.backup (never commit either file)
	cp .env .env.backup
	@echo ".env backed up to .env.backup"

clean:           ## Remove stopped containers and dangling images (data stays in database)
	docker compose down --remove-orphans
	docker image prune -f

##@ Help
help:            ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
