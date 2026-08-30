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
