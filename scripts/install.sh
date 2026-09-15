#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Uso: ./scripts/install.sh [--port PORTA] [--bind ENDEREÇO] [--yes-xorg] [--skip-ufw]
     ./scripts/install.sh --print-dependencies

Instala o Local Remote Control para o usuário atual no Ubuntu.
Execute como usuário normal; o script pedirá sudo somente para pacotes e GDM.
EOF
}

dependencies=(
  python3 python3-venv python3-pip python3-gi
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-bad-1.0
  gstreamer1.0-tools gstreamer1.0-x gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad
  gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-nice
  xdotool xclip openssl
)

port=8443
bind_address=0.0.0.0
yes_xorg=false
skip_ufw=false
print_dependencies=false
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --port) port="${2:?informe a porta}"; shift 2 ;;
    --bind) bind_address="${2:?informe o endereço}"; shift 2 ;;
    --yes-xorg) yes_xorg=true; shift ;;
    --skip-ufw) skip_ufw=true; shift ;;
    --print-dependencies) print_dependencies=true; shift ;;
    *) echo "Opção desconhecida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$print_dependencies" == true ]]; then
  printf '%s\n' "${dependencies[@]}"
  exit 0
fi

if [[ ! "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
  echo "Porta inválida: $port" >&2
  exit 2
fi
if [[ $(id -u) -eq 0 ]]; then
  echo "Não execute o instalador como root. Use seu usuário normal." >&2
  exit 1
fi
if [[ ! -r /etc/os-release ]]; then
  echo "Não foi possível identificar o sistema operacional." >&2
  exit 1
fi
. /etc/os-release
if [[ "${ID:-}" != ubuntu ]]; then
  echo "Este instalador suporta somente Ubuntu." >&2
  exit 1
fi

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
app_dir="${HOME}/.local/share/local-remote-control"
config_dir="${HOME}/.config/local-remote-control"
state_dir="${HOME}/.local/state/local-remote-control"
unit_dir="${HOME}/.config/systemd/user"
config_file="${config_dir}/config.env"

echo "Instalando dependências nativas…"
sudo apt-get update
sudo apt-get install -y "${dependencies[@]}"

umask 077
mkdir -p "$app_dir" "$config_dir" "$state_dir" "$unit_dir"
install -m 0644 "$source_dir/pyproject.toml" "$app_dir/pyproject.toml"
rm -rf "$app_dir/src"
cp -a "$source_dir/src" "$app_dir/src"
python3 -m venv --system-site-packages "$app_dir/venv"
"$app_dir/venv/bin/pip" install --disable-pip-version-check --upgrade "$app_dir"

read -r -s -p "Defina a senha do acesso remoto: " password
echo
read -r -s -p "Repita a senha: " password_confirmation
echo
if [[ -z "$password" || "$password" != "$password_confirmation" ]]; then
  unset password password_confirmation
  echo "As senhas estão vazias ou não coincidem." >&2
  exit 1
fi
password_hash=$(printf '%s' "$password" | "$app_dir/venv/bin/python" -c 'import sys; from argon2 import PasswordHasher; print(PasswordHasher().hash(sys.stdin.read()))')
unset password password_confirmation

host_ip=$(hostname -I | awk '{print $1}')
if [[ -z "$host_ip" ]]; then
  echo "Não foi possível detectar um endereço IPv4 da LAN." >&2
  exit 1
fi
certificate="$config_dir/certificate.pem"
private_key="$config_dir/private-key.pem"
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
  -keyout "$private_key" -out "$certificate" \
  -subj "/CN=$host_ip" -addext "subjectAltName=IP:$host_ip"
chmod 0600 "$private_key" "$certificate"

cat >"$config_file" <<EOF
BIND_HOST=$bind_address
PORT=$port
PUBLIC_HOST=$host_ip
PASSWORD_HASH=$password_hash
CERTIFICATE=$certificate
PRIVATE_KEY=$private_key
SESSION_IDLE_SECONDS=1800
MAX_CLIPBOARD_BYTES=1048576
DISPLAY=:0
SHELL=${SHELL:-/bin/bash}
EOF
chmod 0600 "$config_file"

install -m 0644 "$source_dir/packaging/local-remote-control.service" "$unit_dir/local-remote-control.service"
systemctl --user daemon-reload
systemctl --user enable local-remote-control.service

needs_reboot=false
if [[ "${XDG_SESSION_TYPE:-}" == wayland ]] && [[ -f /etc/gdm3/custom.conf ]]; then
  if [[ "$yes_xorg" != true ]]; then
    read -r -p "Wayland detectado. Configurar Xorg para acesso automático? [S/n] " answer
    [[ "${answer:-S}" =~ ^[Ss]$ ]] || { echo "Instalação interrompida: Xorg é necessário." >&2; exit 1; }
  fi
  sudo cp -n /etc/gdm3/custom.conf /etc/gdm3/custom.conf.local-remote-control.bak || true
  if grep -qE '^[#[:space:]]*WaylandEnable=' /etc/gdm3/custom.conf; then
    sudo sed -i 's/^[#[:space:]]*WaylandEnable=.*/WaylandEnable=false/' /etc/gdm3/custom.conf
  else
    sudo sed -i '/\[daemon\]/a WaylandEnable=false' /etc/gdm3/custom.conf
  fi
  needs_reboot=true
fi

if [[ "$skip_ufw" != true ]] && command -v ufw >/dev/null && sudo ufw status | grep -q '^Status: active'; then
  default_interface=$(ip route show default | awk 'NR==1 {print $5}')
  address_cidr=$(ip -o -4 address show dev "$default_interface" scope global | awk 'NR==1 {print $4}')
  lan_subnet=$("$app_dir/venv/bin/python" -c 'import ipaddress,sys; print(ipaddress.ip_network(sys.argv[1], strict=False))' "$address_cidr")
  sudo ufw allow from "$lan_subnet" to any port "$port" proto tcp comment 'Local Remote Control LAN'
fi

if [[ "$needs_reboot" == true ]]; then
  echo "Instalação concluída. Reinicie o notebook para ativar o Xorg."
else
  systemctl --user restart local-remote-control.service
  echo "Instalação concluída e serviço iniciado."
fi
echo "Abra no notebook do quarto: https://${host_ip}:${port}"
echo "Logs: journalctl --user -u local-remote-control -f"
