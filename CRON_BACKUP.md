# Backup com cron-job.org

Os jobs externos devem rodar depois dos horarios principais:

- `13:15` para conferir a publicacao das `12:45` (`slot=1245`)
- `20:00` para conferir a publicacao das `19:30` (`slot=1930`)

Use o timezone `America/Sao_Paulo`. Cada job dispara o workflow
`instagram-publisher.yml` com `dry_run=false` e seu respectivo `slot`.

O arquivo `state/published.json` registra tambem `data+slot`. Se o
agendamento normal do GitHub ja tiver concluido aquela publicacao, a
execucao de backup termina sem publicar outro Reel. A concorrencia do
workflow serializa uma execucao atrasada e o backup para que ambos leiam
o estado mais recente.

## Requisicao dos dois jobs

URL:

```text
https://api.github.com/repos/LuisFelipe1-star/PUBLICATION_MANAGER_AUTOMATICO/actions/workflows/instagram-publisher.yml/dispatches
```

Metodo: `POST`

Headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer SEU_TOKEN_FINE_GRAINED
Content-Type: application/json
X-GitHub-Api-Version: 2022-11-28
```

O token deve ter acesso somente a este repositorio e permissao
`Actions: Read and write`. Nunca registre o token neste arquivo.

Corpo do job das 13:15:

```json
{"ref":"master","inputs":{"dry_run":"false","slot":"1245"}}
```

Corpo do job das 20:00:

```json
{"ref":"master","inputs":{"dry_run":"false","slot":"1930"}}
```

Para um teste sem publicar, use temporariamente:

```json
{"ref":"master","inputs":{"dry_run":"true","slot":"manual"}}
```
