# Checklist manual de aceitação no Ubuntu

Registre versão do Ubuntu, GPU, sessão, navegador e resultado de cada item.

## Instalação e boot

- [ ] Instalação nova termina sem executar o serviço como root.
- [ ] Segunda execução do instalador atualiza sem duplicar configuração systemd.
- [ ] Wayland é detectado, a troca para Xorg é confirmada e o backup do GDM existe.
- [ ] Após reiniciar, `echo "$XDG_SESSION_TYPE"` retorna `x11`.
- [ ] Login automático abre a área de trabalho e o serviço fica `active (running)`.
- [ ] A URL impressa abre a partir de outro dispositivo na mesma LAN.

## Segurança

- [ ] Senha incorreta é rejeitada e cinco erros ativam espera progressiva.
- [ ] Cookie da sessão tem `Secure`, `HttpOnly` e `SameSite=Strict`.
- [ ] Requisições sem CSRF e WebSockets de outra origem são recusados.
- [ ] Um segundo navegador recebe aviso de sessão ocupada.
- [ ] O serviço não responde por uma rede fora da sub-rede autorizada pelo UFW.
- [ ] Não há encaminhamento da porta no roteador.

## Tela e controles

- [ ] Chrome recebe vídeo, controla ponteiro, botões, roda e teclado.
- [ ] Firefox recebe vídeo, controla ponteiro, botões, roda e teclado.
- [ ] `Ctrl + Alt + Shift` libera o teclado local.
- [ ] Fechar a aba libera o controle após o timeout.
- [ ] Suspender e retomar a rede permite reconectar sem reiniciar o host.
- [ ] Vídeo é testado com NVENC, VA-API ou x264 conforme o hardware disponível.
- [ ] O fallback x264 inicia quando o encoder por hardware é indisponibilizado.

## Clipboard e terminal

- [ ] Texto copiado no host remoto pode ser recebido no dispositivo cliente.
- [ ] Texto copiado no dispositivo cliente pode ser enviado e colado no host remoto.
- [ ] Clipboard negado pelo navegador apresenta a caixa de fallback.
- [ ] Conteúdo maior que 1 MiB é rejeitado sem derrubar a sessão.
- [ ] Terminal abre com o usuário do login automático.
- [ ] Terminal recebe entrada, cores, redimensionamento e saída longa.
- [ ] Desconectar encerra o processo PTY.

## Operação

- [ ] `scripts/diagnose.sh` não revela hash, token, CSRF ou chave privada.
- [ ] `systemctl --user restart local-remote-control` recupera o serviço.
- [ ] `scripts/uninstall.sh` remove somente arquivos próprios e preserva o backup do GDM.
