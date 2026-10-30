#!/bin/sh
# tts-gateway-fw: DOCKER-USER-Lockdown fuer den TTS-Job-Bus (host:8146).
#
# Der Gateway bindet bewusst 0.0.0.0:8146: die host-mode-Konsumenten (host-router,
# wyoming-tts-bridge) UND die Bridge-Konsumenten (life-ops, saganta-news) erreichen
# ihn nur ueber die host-LAN-IP .11, denn 127.0.0.1 wuerde die Bridge-Container
# abschneiden. Statt zu rebinden wird der Zugriff auf Port 8146 per DOCKER-USER auf
# vertrauenswuerdige Quellen begrenzt. Der Gateway ist der einzige Sprecher vor dem
# XTTS-Backend (.22:5002, dessen INPUT-fw wiederum nur .11 erlaubt) und darf nicht von
# beliebigen LAN-Hosts/VPN-Clients erreichbar sein.
#
# WICHTIG: DOCKER-USER (FORWARD/filter) sieht Pakete an published Container-Ports NACH
# DNAT. Der ORIGINALE Zielport wird deshalb ueber conntrack --ctorigdstport 8146
# gematcht (stabil gegen Container-IP-Aenderung). Ein simples "--dport 8146" griffe ins Leere.
#
# Regel-Modell (deny-spezifisch, wie llm-gateway-fw):
#   RETURN  von host (.11)                     -> erlaubt (host-mode-Konsumenten + Host)
#   DROP    vom restlichen LAN 192.0.2.10/24    -> geblockt
#   DROP    von WireGuard-Clients 192.0.2.10/24    -> geblockt
#   (host-eigene Docker-Bridges cc-apps/cc-core etc. fallen durch -> die LOKALEN
#    Bridge-Konsumenten life-ops/saganta-news erreichen den Gateway; deny-spezifisch
#    trifft nur untrusted Quellen.)
#
# Der vorgesehene Erweiterungsweg ist eingetreten: .12 steht seit 2026-10-13 in ALLOW,
# weil das Karten-Portal auf node1 die Navi-Ansagen hier holt (`location /tts/` in
# karten/nginx.conf). Damit vermittelt der Gateway XTTS/Piper fuer node1, OHNE die
# XTTS-INPUT-fw (.22 nur .11) aufzuweichen -- genau die Rolle, fuer die er gebaut ist.
# Port 8147 (ntfy) traegt dieselbe Freigabe schon.
#
# Idempotent. Deploy-Ziel: host -> /usr/local/sbin/tts-gateway-fw.sh (systemd-Oneshot).
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
