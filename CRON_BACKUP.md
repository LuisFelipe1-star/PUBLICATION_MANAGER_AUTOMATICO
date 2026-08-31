# Agendamento externo

O workflow não possui `schedule` nativo. Estes são os únicos disparos automáticos autorizados:

- `13:15` em `America/Sao_Paulo`, representando o slot editorial `12:45`;
- `20:00` em `America/Sao_Paulo`, representando o slot editorial `19:30`.

Cada job chama:

```text
POST https://api.github.com/repos/LuisFelipe1-star/PUBLICATION_MANAGER_AUTOMATICO/actions/workflows/instagram-publisher.yml/dispatches
```

Headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer SEU_TOKEN_FINE_GRAINED
Content-Type: application/json
X-GitHub-Api-Version: 2022-11-28
```

O token deve ficar somente no serviço de agendamento, limitado a este repositório e com `Actions: Read and write`.

Corpo das 13:15:

```json
{"ref":"master","inputs":{"dry_run":"false","slot":"1245"}}
```

Corpo das 20:00:

```json
{"ref":"master","inputs":{"dry_run":"false","slot":"1930"}}
```

Teste sem publicação:

```json
{"ref":"master","inputs":{"dry_run":"true","slot":"manual"}}
```

O arquivo `state/published.json` guarda o slot concluído e uma possível reserva `inflight`. Uma reserva pendente bloqueia novas publicações automáticas até revisão manual.
