# Quadro de Tarefas — Ha'evete

Versão independente do quadro de tarefas (antes um Claude Artifact que dependia de
`window.storage`, que só funciona dentro do Claude.ai). Agora é um app comum:
**Flask (backend) + HTML/JS estático (frontend)**, com um arquivo JSON compartilhado
como banco de dados. Qualquer pessoa que abrir o link vê o mesmo estado, e o
front-end busca atualizações a cada 18s (mais um botão "atualizar agora").

## Rodando localmente

```bash
python -m pip install -r requirements.txt
python app.py
```

Abra `http://localhost:5000`.

O estado fica salvo em `data/state.json` (criado automaticamente). Esse arquivo
**não** deve ir para o Git — já está no `.gitignore`.

## Como funciona

- `app.py` — API Flask. Cada tarefa tem `status`, um `responsavel` (só 1,
  opcional) e até 3 `auxiliares`:
  - `GET /api/state` → devolve o estado de todas as tarefas
  - `POST /api/state/<id>/status` → muda o status (clicando no badge do card)
  - `POST /api/state/<id>/responsavel` · `DELETE /api/state/<id>/responsavel`
    → assume/edita/limpa o responsável
  - `POST /api/state/<id>/auxiliares` → adiciona um auxiliar (máx. 3)
  - `POST /api/state/<id>/auxiliares/<aux_id>` · `DELETE .../auxiliares/<aux_id>`
    → edita/remove um auxiliar específico
  - Todos os endpoints de escrita têm rate limit simples (20 req/min por IP)
  - Serve `static/index.html` na raiz `/`
  - `load_state()` migra automaticamente registros salvos no formato antigo
    (versão anterior, sem responsável/auxiliares) sem perder dados
- `static/index.html` — a lista fixa das 35 tarefas (categoria, prioridade,
  título, descrições) fica **hardcoded no HTML**, exatamente como no artifact
  original, porque a spec pede que isso não seja editável pelos usuários.
- A tarefa `f3` (LOAS/Bolsa Família) já nasce com responsável "Kayo" e
  `status: "em-andamento"`, igual à versão original.

Se algum dia precisar editar o texto de uma tarefa (título, descrição,
prioridade), edite o array `tasks` no topo do `<script>` em `static/index.html`.

## ⚠️ Importante: rodar com 1 worker só

O estado fica em memória (espelhado num arquivo JSON) dentro do processo
Flask — **não é seguro rodar mais de um worker/processo** ao mesmo tempo,
porque cada um teria sua própria cópia do estado e ficariam brigando pra
escrever no arquivo. O `Procfile` e o `Dockerfile` já estão configurados com
`--workers 1`. Para esse uso (dezenas de voluntários, updates esporádicos),
1 worker aguenta numa boa.

Se um dia o tráfego crescer muito e isso virar gargalo, o caminho é trocar o
arquivo JSON por SQLite ou Postgres — mas para o volume desse quadro (35
tarefas, poucas escritas por dia) não é necessário.

## Deploy (hospedagem pública)

Qualquer serviço que rode uma imagem Docker ou um app Python com `Procfile`
funciona. Duas opções simples:

### Opção A — Render.com
1. Suba esta pasta para um repositório no GitHub.
2. No Render, crie um **Web Service** apontando pro repo.
3. Build command: `pip install -r requirements.txt` · Start command:
   `gunicorn --bind 0.0.0.0:$PORT --workers 1 app:app`
4. **Adicione um "Persistent Disk"** montado em `/opt/render/project/src/data`
   (Render > seu serviço > Disks) — sem isso, o `state.json` some a cada
   deploy/redeploy (fica só durante a vida do container). Um disco pequeno
   (1 GB) já é suficiente e tem custo mínimo.

### Opção B — Railway.app
1. Suba o repo para o GitHub e conecte no Railway.
2. Railway detecta o `Procfile` automaticamente.
3. Adicione um **Volume** montado em `/app/data` (Railway > seu serviço >
   Volumes) para persistir o `state.json` entre deploys.

Nas duas opções, sem o disco/volume persistente o quadro ainda funciona
enquanto o container não reiniciar — mas qualquer redeploy (ex: você editando
o texto de uma tarefa) apaga os dados preenchidos pelos voluntários. Por isso
o disco persistente é recomendado antes de divulgar o link.

## Proteção contra spam

Rate limit simples (20 requisições/minuto por IP) já embutido no backend —
sem necessidade de login, como pedido na spec.
