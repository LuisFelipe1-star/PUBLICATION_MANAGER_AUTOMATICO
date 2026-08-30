# Publication Manager Automático

Consome recursivamente a saída do Auto Video Cutter, valida MP4 + TXT estáveis com FFprobe, registra no SQLite, agenda toda a fila e publica Reels continuamente. SRT é opcional; `metadata.json` é usado quando existe. O TXT é enviado literalmente, sem reescrita.

## Instalação no Windows

1. Instale Python 3.10 ou 3.11 e FFmpeg/FFprobe no PATH.
2. Execute `install_windows.bat`.
3. Copie `.env.example` para `.env` e informe `META_APP_ID`, `META_APP_SECRET`, `META_LOGIN_CONFIG_ID` e o redirect URI registrado na Meta.
4. Execute `run_windows.bat`.

Em **Configurações**, use **Detectar automaticamente** ou **Escolher pasta** e selecione a raiz do Auto Video Cutter. O programa lê `folders.input` e `folders.output` do config real; não há caminho de usuário fixo. A detecção só procura o projeto, pais e diretórios vizinhos.

## Fluxo automático

Mantenha **Modo teste** ligado, habilite Facebook/Instagram após conectar via Facebook Login for Business e clique **INICIAR**. O botão faz scanner, validação, SQLite, agendamento automático, scheduler e monitoramento contínuo. O padrão é amanhã às 12:45, depois 19:30, sempre no timezone configurado. O botão **Agendar fila** virou apenas ferramenta manual.

Reinícios preservam o SQLite. Itens `PUBLICANDO` interrompidos vão para `REVISAO`; horários perdidos são reagendados por padrão, sem disparo em massa. **Iniciar com o Windows** cria um único launcher na pasta Startup e o mutex impede duas instâncias.

## Publicação real

Teste primeiro e confira a fila. Ao desligar **Modo teste**, confirme o aviso de publicação real. Tokens continuam no Windows Credential Manager via keyring; o OAuth usa `config_id`, descobre Páginas e Instagram profissional, e nunca pede token manual.

## Testes

`python -m unittest discover -s tests -v`

## Permissões e estado

Se a pasta do projeto estiver protegida pelo Windows, o programa mantém o SQLite e a configuração editável em `%LOCALAPPDATA%\\PublicationManager` (ou em `%TEMP%\\PublicationManager` quando o primeiro local não for gravável). É possível definir outro local com `PM_STATE_DIR`; `PM_LOG_FILE` altera apenas o arquivo de log. Os vídeos continuam sendo lidos diretamente da pasta `saida` configurada.

O modo teste vem ativado e as plataformas vêm desativadas. Para publicar de verdade: conecte a Meta, confirme a publicação real no aviso da interface e habilite Facebook/Instagram. Sem esses passos o programa apenas agenda e simula, evitando posts acidentais.
## PublicaÃ§Ã£o sem o PC ligado (GitHub Actions)

O workflow `.github/workflows/instagram-publisher.yml` publica somente no Instagram em 12:45 e 19:30 em `America/Sao_Paulo` (cron UTC: `45 15` e `30 22`). Ele publica no mÃ¡ximo um corte por execuÃ§Ã£o e registra o ID em `state/published.json`.

1. No GitHub Desktop, abra esta pasta e use **Publish repository**. Escolha um repositÃ³rio pÃºblico; `.env` e `config.json` jÃ¡ estÃ£o ignorados.
2. Crie uma Release `videos-v1` no GitHub e envie os 38 MP4. Em **Settings > Secrets and variables > Actions**, crie `IG_USER_ID`, `IG_ACCESS_TOKEN`, `GRAPH_VERSION` e a variable `VIDEO_BASE_URL` com `https://github.com/USUARIO/REPOSITORIO/releases/download/videos-v1`.
3. Execute o workflow manualmente com `dry_run=true`. Depois de conferir o log, as execuÃ§Ãµes agendadas publicarÃ£o de verdade.

O GitHub Actions pode atrasar alguns minutos. O token da Meta precisa ser renovado periodicamente. A API exige Instagram profissional vinculado a uma PÃ¡gina da Meta, embora nenhum post seja enviado ao Facebook.
