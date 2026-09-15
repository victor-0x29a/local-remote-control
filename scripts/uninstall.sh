#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Uso: ./scripts/uninstall.sh [--yes]

Desativa o serviço e remove somente arquivos pertencentes ao Local Remote Control.
Pacotes APT, backup do GDM e regras UFW são preservados para evitar perda acidental.
EOF
}

confirmed=false
case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --yes) confirmed=true ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac
if [[ $(id -u) -eq 0 ]]; then
  echo "Execute como o usuário que instalou o aplicativo, não como root." >&2
  exit 1
fi
if [[ "$confirmed" != true ]]; then
  read -r -p "Remover o Local Remote Control deste usuário? [s/N] " answer
  [[ "$answer" =~ ^[Ss]$ ]] || { echo "Cancelado."; exit 0; }
fi

systemctl --user disable --now local-remote-control.service 2>/dev/null || true
unit_file="${HOME}/.config/systemd/user/local-remote-control.service"
app_dir="${HOME}/.local/share/local-remote-control"
config_dir="${HOME}/.config/local-remote-control"
state_dir="${HOME}/.local/state/local-remote-control"
rm -f "$unit_file"
rm -rf "$app_dir" "$config_dir" "$state_dir"
systemctl --user daemon-reload
echo "Aplicativo removido. Pacotes Ubuntu, firewall e configuração do GDM não foram alterados."
