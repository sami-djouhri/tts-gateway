#!/bin/sh
set -eu

PORT=8146
# .12 ist KEINE Lockerung ins Blaue: der Browser spricht nie selbst mit diesem
#   Port. Er ruft seinen eigenen Ursprung (karten.home.arpa) an, node1-nginx
#   holt die Sprachdatei hier, und nur node1 braucht deshalb Durchlass. Ein Handy
#   im WLAN oder am VPN bleibt geblockt, siehe DENY.
ALLOW="192.0.2.10 192.0.2.10"    # host (alle lokalen Konsumenten) + node1 (karten-Navi)
DENY="192.0.2.10/24 192.0.2.10/24"    # restlicher LAN + WireGuard

CT="-m conntrack --ctorigdstport ${PORT}"

# --- 1. eigene Regeln entfernen (idempotent) ---
for S in $ALLOW; do
  # shellcheck disable=SC2086
  iptables -D DOCKER-USER -p tcp $CT -s "$S" -j RETURN 2>/dev/null || true
done
for S in $DENY; do
  # shellcheck disable=SC2086
  iptables -D DOCKER-USER -p tcp $CT -s "$S" -j DROP 2>/dev/null || true
done

# --- 2. in umgekehrter Zielreihenfolge oben einfuegen (RETURNs landen ueber DROPs) ---
for S in $DENY; do
  # shellcheck disable=SC2086
  iptables -I DOCKER-USER 1 -p tcp $CT -s "$S" -j DROP
done
for S in $ALLOW; do
  # shellcheck disable=SC2086
  iptables -I DOCKER-USER 1 -p tcp $CT -s "$S" -j RETURN
done

echo "tts-gateway-fw: aktiv (Port ${PORT}): RETURN[${ALLOW}] DROP[${DENY}]"
