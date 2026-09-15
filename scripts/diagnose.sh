#!/usr/bin/env bash
set -u

usage() {
  cat <<'EOF'
Uso: ./scripts/diagnose.sh [--help]

Mostra estado do serviço, sessão gráfica, porta e encoders sem revelar segredos.
EOF
}

case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac

config_file="${HOME}/.config/local-remote-control/config.env"
echo "Local Remote Control — diagnóstico"
echo "Sessão: ${XDG_SESSION_TYPE:-desconhecida}; DISPLAY=${DISPLAY:-não definido}"
echo "Python: $(python3 --version 2>&1)"
echo "GStreamer: $(gst-launch-1.0 --version 2>/dev/null | head -n1 || echo ausente)"
echo "Encoders H.264 disponíveis:"
for encoder in nvh264enc vah264enc vaapih264enc x264enc; do
  gst-inspect-1.0 "$encoder" >/dev/null 2>&1 && echo "  - $encoder"
done
if [[ -r "$config_file" ]]; then
  port=$(sed -n 's/^PORT=//p' "$config_file")
  public_host=$(sed -n 's/^PUBLIC_HOST=//p' "$config_file")
  echo "URL configurada: https://${public_host:-?}:${port:-?}"
  command -v ss >/dev/null && ss -ltn "sport = :${port:-0}" 2>/dev/null || true
else
  echo "Configuração: ausente"
fi
systemctl --user --no-pager status local-remote-control.service 2>&1 || true
echo "Últimas mensagens (segredos filtrados):"
journalctl --user -u local-remote-control.service -n 30 --no-pager 2>&1 \
  | sed -E 's/(PASSWORD_HASH|PRIVATE_KEY|csrf|token)=[^ ]+/\1=<redigido>/Ig'
