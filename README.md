# Local Remote Control

Controle um notebook Ubuntu pela rede local usando somente o navegador do outro notebook. A aplicação transmite a tela com WebRTC/H.264, recebe mouse e teclado, abre um terminal com o usuário já logado e sincroniza texto da área de transferência.

Não há nuvem, relay externo, áudio ou transferência de arquivos. Uma única sessão pode controlar o notebook por vez.

## Antes de instalar

No notebook da sala, confirme:

- Ubuntu com login automático já configurado;
- conexão à mesma rede Wi-Fi ou cabeada do notebook do quarto;
- acesso a uma conta com `sudo` durante a instalação;
- internet apenas durante a instalação dos pacotes Ubuntu e Python;
- nenhum encaminhamento de porta configurado no roteador para a porta da aplicação.

O instalador pode trocar Wayland por Xorg. Isso é necessário para capturar e controlar a sessão automaticamente depois de reiniciar, sem alguém precisar confirmar o compartilhamento na tela da sala.

## Instalação no notebook da sala

Abra um terminal no notebook da sala e entre na pasta deste projeto. Se recebeu a pasta por pendrive ou compartilhamento, por exemplo:

```bash
cd ~/Downloads/local-remote-control
```

Garanta que os scripts podem ser executados:

```bash
chmod +x scripts/*.sh
```

Execute o instalador como seu usuário normal — não use `sudo` antes do script:

```bash
./scripts/install.sh
```

O próprio instalador solicitará `sudo` somente para instalar pacotes do Ubuntu e, se preciso, configurar o GDM para usar Xorg. Depois ele pedirá uma senha exclusiva para o acesso remoto. Essa senha não é a senha do Ubuntu; somente seu hash Argon2id será salvo.

Ao terminar, o instalador mostrará um endereço semelhante a:

```text
https://192.168.1.35:8443
```

Se Wayland estiver ativo, o script solicitará um reinício. Salve seu trabalho e execute:

```bash
sudo reboot
```

Como o login automático já está configurado, o serviço iniciará depois que a área de trabalho Xorg abrir.

### Opções do instalador

```bash
./scripts/install.sh --port 9443
./scripts/install.sh --yes-xorg
./scripts/install.sh --skip-ufw
./scripts/install.sh --help
```

- `--port`: muda a porta HTTPS; a padrão é `8443`.
- `--yes-xorg`: autoriza antecipadamente a troca de Wayland para Xorg.
- `--skip-ufw`: não cria a regra restrita à sub-rede quando o UFW está ativo.

O instalador pode ser executado novamente para atualizar uma instalação existente. Ele substitui o código do aplicativo, preservando somente dados que recria de maneira controlada, e reinicia o serviço quando não há reinício pendente.

## Conectar pelo notebook do quarto

1. Conecte o notebook do quarto à mesma LAN.
2. Abra Chrome ou Firefox.
3. Digite exatamente a URL HTTPS mostrada pelo instalador.
4. Na primeira abertura, o navegador alertará que o certificado é local e não foi emitido por uma autoridade pública. Confira se o endereço IP é o do notebook da sala e aceite a exceção uma única vez.
5. Informe a senha criada durante a instalação.
6. Clique dentro da tela remota para capturar teclado e mouse.

Use `Ctrl + Alt + Shift` para liberar o teclado do controle remoto. Atalhos reservados pelo próprio navegador ou sistema operacional, como algumas combinações de troca de janela, podem permanecer locais.

## Área de transferência

A sincronização aceita texto, não imagens ou arquivos.

- Ao copiar texto no Ubuntu da sala, o botão **Colar** avisa que há conteúdo remoto. Clique nele para levar o texto ao clipboard do notebook do quarto.
- Para enviar texto do quarto, copie-o localmente e clique em **Colar** quando não houver conteúdo remoto pendente.
- Também é possível colar texto diretamente com `Ctrl+V` enquanto a tela remota está focada. O navegador envia o texto ao clipboard X11 e então cola no aplicativo remoto.
- Se o navegador negar a permissão de clipboard, a interface abre uma caixa de texto como alternativa. A API exige uma ação explícita do usuário por segurança.

O limite padrão é 1 MiB de texto por atualização.

## Terminal remoto

Clique em **Terminal** na barra superior. O shell é aberto com exatamente o mesmo usuário da sessão automática do notebook da sala. Portanto, ele consegue ler, alterar e apagar os arquivos desse usuário. A senha da aplicação protege tanto a tela quanto o terminal.

Fechar o painel apenas oculta o terminal. Desconectar encerra a sessão PTY e libera o controle para outra conexão.

## Gerenciar o serviço

No notebook da sala:

```bash
systemctl --user status local-remote-control
systemctl --user restart local-remote-control
systemctl --user stop local-remote-control
systemctl --user start local-remote-control
journalctl --user -u local-remote-control -f
```

O serviço começa com a sessão gráfica e reinicia automaticamente se o processo falhar.

## Diagnóstico

Execute:

```bash
./scripts/diagnose.sh
```

O relatório mostra sessão gráfica, URL, porta, estado do serviço e encoders H.264 encontrados, sem imprimir hash de senha ou chave TLS.

Problemas comuns:

- **A página não abre:** confirme o IP mostrado por `hostname -I`, verifique `systemctl --user status local-remote-control` e teste se ambos estão na mesma rede.
- **Serviço falha após ligar:** veja `journalctl --user -u local-remote-control -b`; confirme que o login automático chegou à área de trabalho.
- **Sem vídeo:** execute `gst-inspect-1.0 x264enc` e confirme que a sessão mostra `x11` em `echo "$XDG_SESSION_TYPE"`.
- **Mouse ou teclado não responde:** rode `DISPLAY=:0 xdotool getdisplaygeometry` no notebook da sala e verifique se o comando consegue acessar a tela.
- **Certificado mudou:** isso ocorre ao reinstalar; confirme novamente o IP antes de aceitar a nova exceção.
- **Mensagem de sessão ocupada:** feche a aba controladora anterior ou aguarde cerca de 15 segundos para o lease expirar.

## Segurança da rede

Este software oferece controle total e terminal. Use somente em uma LAN confiável.

- Nunca encaminhe a porta `8443` (ou a porta escolhida) no roteador.
- Não exponha o serviço diretamente à internet.
- Escolha uma senha longa e diferente da senha do Ubuntu.
- O instalador restringe a porta à sub-rede detectada se o UFW já estiver ativo.
- Sessões expiram após 30 minutos sem atividade e são apagadas quando o serviço reinicia.
- Cinco tentativas incorretas ativam espera progressiva por endereço de origem.

## Desinstalar

Na pasta do projeto, execute:

```bash
./scripts/uninstall.sh
```

O script desativa o serviço e remove apenas os arquivos da aplicação pertencentes ao usuário atual. Ele preserva pacotes compartilhados do Ubuntu, regras do firewall e o backup `/etc/gdm3/custom.conf.local-remote-control.bak`.

Se quiser voltar ao Wayland, restaure manualmente a configuração do GDM somente depois de conferir o backup:

```bash
sudo diff -u /etc/gdm3/custom.conf /etc/gdm3/custom.conf.local-remote-control.bak
```

## Desenvolvimento e testes

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
node --test tests/client_protocol.test.mjs
bash -n scripts/*.sh
```

Os testes de integração HTTP abrem somente uma porta efêmera no loopback durante a execução. A validação completa de captura, encoder e inicialização após boot precisa ser feita em um Ubuntu com sessão gráfica; consulte `docs/manual-acceptance.md`.
