# Publication Manager Automático

O publicador oficial deste projeto é o GitHub Actions. O aplicativo Windows permanece em modo seguro para detectar arquivos, validar o Cutter e consultar a fila, mas não publica enquanto `publisher_backend` for `github_actions`.

## Fluxo oficial

1. O Auto Video Cutter gera MP4 e `metadata.json`.
2. `scripts/sync_release.py` transforma a ordem global do metadata em `parte_XX.mp4`, preserva legendas já revisadas e atualiza `state/manifest.json`.
3. O mesmo comando pode preparar os assets e sincronizar a Release usando GitHub CLI.
4. Os disparos externos executam `.github/workflows/instagram-publisher.yml`.
5. Antes de chamar a Meta, o workflow grava e envia uma reserva em `state/published.json`.
6. Depois da resposta da Meta, o resultado é persistido e somente então a fila é finalizada.

Esse protocolo prefere interromper a fila para revisão a correr o risco de publicar o mesmo Reel duas vezes.

## Horários

Os horários editoriais são `12:45` e `19:30` em `America/Sao_Paulo`. O workflow não possui cron nativo. Os dois agendamentos oficiais são externos:

- `13:15`, enviando `slot=1245`;
- `20:00`, enviando `slot=1930`.

Consulte [CRON_BACKUP.md](CRON_BACKUP.md) para a requisição exata. Não mantenha outro agendador ou o aplicativo desktop publicando ao mesmo tempo.

## Preparar manifesto e Release

Instale e autentique o GitHub CLI antes de usar `--upload`.

```powershell
python scripts/sync_release.py `
  --metadata "C:\caminho\para\saida\Video\metadata.json" `
  --manifest state/manifest.json `
  --overrides state/content_overrides.json `
  --asset-dir "C:\caminho\para\release-assets" `
  --start-order 17 `
  --repo LuisFelipe1-star/PUBLICATION_MANAGER_AUTOMATICO `
  --tag videos-v1
```

O comando acima apenas prepara os arquivos. Acrescente `--upload` depois de revisar o manifesto e o relatório. Arquivos remotos com o mesmo nome e tamanho não são reenviados.

Valide antes de publicar:

```powershell
python scripts/validate_manifest.py --report CONTENT_REVIEW.md
python -m unittest discover -s tests -v
```

## Configuração do GitHub

Secrets:

- `IG_USER_ID`
- `IG_ACCESS_TOKEN`
- `GRAPH_VERSION` opcional, com padrão `v26.0`

Variables:

- `VIDEO_BASE_URL`, apontando para a Release;
- `PUBLISHING_ENABLED=true` somente depois do dry run.

Execute primeiro o workflow manual com `dry_run=true`. Falhas reais abrem ou atualizam uma issue de alerta no repositório.

## Reserva pendente

Se `state/published.json` contiver `inflight`, não execute novamente até conferir o Instagram:

- se o Reel existe, altere a reserva para `status: published`, registre `instagram_media_id` e execute a fase `finalize`;
- se o Reel não existe e a Meta confirma que nada foi publicado, remova a reserva em um commit revisado e tente novamente;
- se houver dúvida, mantenha a reserva. A fila deve ficar parada.

## Aplicativo Windows

1. Execute `install_windows.bat`.
2. Crie `.env` a partir de `.env.example`.
3. Execute `run_windows.bat`.

Para transferir a publicação oficial ao desktop, primeiro desative todos os disparos externos e depois defina `publisher_backend` como `desktop`. O modo teste continua obrigatório antes da publicação real.

## Estado local

SQLite, configuração e logs usam `%LOCALAPPDATA%\PublicationManager` quando possível. `PM_STATE_DIR` e `PM_LOG_FILE` permitem alterar esses locais. `.env`, `config.json`, banco e logs não são versionados.

## Direitos e armazenamento

Confirme os direitos de publicação de todo conteúdo antes do envio. GitHub Releases funciona para o lote atual, mas não deve ser tratado como CDN permanente para uma biblioteca crescente de vídeos.
