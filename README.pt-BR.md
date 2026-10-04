# devin-skill-catalog

> **Projeto comunitário não-oficial.** Não é afiliado, endossado nem
> patrocinado pela Cognition AI. "Devin" é marca da Cognition AI.

**[English](README.md)** · Português (BR)

O `devin-skill-catalog` inventaria, linta, coloca em quarentena e
promove as skills `SKILL.md` e regras `rules/*.md` que vivem em dirs
`.devin/` — no nível do workspace e do usuário. Ele adiciona um registro
de ciclo de vida, diff de inventário entre workspaces, dois gates de
evidência offline e um formato de bundle portátil para que itens
aprovados circulem entre máquinas **passando pela** quarentena — nunca
a contornando.

## O problema

`.devin/skills/` e `.devin/rules/` acumulam conteúdo de todo lado —
escrito à mão, copiado de outros repos, colado de um chat. Nada responde
às perguntas básicas: *o que está instalado e onde? essa skill mudou
entre meus workspaces? essa regra contém frase de injeção ou uma chave
de API colada? e quais desses itens eu realmente revisei?*

O `devin-skill-catalog` é o inventário + gate de supply chain desse
conteúdo.

## O que faz

- **Inventário** — varre `.devin/skills/<nome>/SKILL.md` e
  `.devin/rules/*.md`, gera hash sha256 por item e anota com o estado no
  registro.
- **Lint** — checagens estruturais: presença de frontmatter, `name`
  igual ao nome do diretório, `description` de verdade, títulos `# `
  nas regras.
- **Gates** — dois gates de evidência offline (abaixo). Heurísticas,
  **não prova**.
- **Ciclo de vida** — um registro em
  `<config-dir>/.devin-ecosystem/skill-catalog.json` acompanha cada item
  por `proposed → quarantined → approved → active → retired`.
- **Diff** — comparação por hash de conteúdo dos inventários de dois
  dirs.
- **Bundles** — exporta itens `approved` para um diretório ou
  `.tar[.gz]` com `manifest.json` (itens, sha256 por arquivo, perfil da
  origem); a importação verifica checksums e deixa os itens em
  **quarentena — nunca diretamente ativos**.

## Instalação

Requer Python ≥ 3.10 e `pipx`. Somente stdlib — sem dependências.

```bash
pipx install "devin-skill-catalog @ git+https://github.com/Icaro0310/devin-skill-catalog.git"
```

(Ainda não publicado no PyPI; a instalação via GitHub acima é o caminho
suportado.)

## Comandos

```bash
devin-skill-catalog scan [PATH ...]              # inventário (somente leitura)
devin-skill-catalog lint [PATH ...]              # achados estruturais
devin-skill-catalog diff A B                     # diff de inventário por sha256
devin-skill-catalog gate g1 PATH                 # gate de higiene estática
devin-skill-catalog gate g2 PATH [--packs-dir D] # gate de fundamentação
devin-skill-catalog quarantine ITEM [PATH ...]   # snapshot → quarantined
devin-skill-catalog promote ITEM [--force]       # quarantined → approved (roda G1)
devin-skill-catalog activate ITEM                # approved → active
devin-skill-catalog retire ITEM                  # qualquer estado → retired
devin-skill-catalog export-bundle --out DIR      # empacota itens aprovados
devin-skill-catalog import-bundle PATH           # itens chegam em quarentena
```

`ITEM` é `kind:name` (`skill:foo`, `rule:bar`) ou o nome puro quando a
resolução não é ambígua. `PATH` aceita raiz de workspace, dir `.devin`,
dir de skill ou arquivo único.

**Mutações plano-primeiro.** `quarantine`, `promote`, `activate`,
`retire` e `import-bundle` imprimem um plano e não escrevem nada sem
`--apply`:

```
$ devin-skill-catalog quarantine skill:demo ./ws
plan:
  quarantine skill:demo (currently proposed)
  copy 1 file(s)  ./ws/.devin/skills/demo
               → ~/.config/devin/.devin-ecosystem/skill-catalog/quarantine/skill/demo
  registry: proposed → quarantined
  note: the original files in .devin/ stay untouched — remove them
        manually if the item must stop loading

nothing written — re-run with --apply to execute
```

**Dirs varridos são read-only.** A ferramenta *nunca* escreve num dir
`.devin/`. Os únicos alvos de escrita são o arquivo de registro e a
store de quarentena sob o config dir do Devin, além do que você apontar
em `--out`. A quarentena tira snapshot do item; remover o original de
`.devin/` é decisão sua.

## Ciclo de vida

```
proposed → quarantined → approved → active → retired
               ↑____________________|          ↓
               (aprovação pode ser revertida;  retired → proposed
                retire funciona de qualquer      (re-propõe)
                estado)
```

- `quarantine` — copia o item para a store de quarentena (fora de
  `.devin/`, então o Devin nunca o carrega) e o marca `quarantined`.
- `promote` — roda **G1 na cópia quarentenada**; um FAIL recusa a
  promoção (`--force` contorna). `quarantined → approved`.
- `activate` — marca o item `active` no catálogo. Instalar os arquivos
  em `.devin/` continua sendo passo manual — esta ferramenta nunca
  escreve lá.
- `retire` — aposenta o item; `retired → proposed` é o único caminho de
  volta.

Itens encontrados no disco sem registro aparecem como não-registrados —
o catálogo não finge ter revisado o que nunca viu.

## Gates

### G1 — higiene estática

As checagens de lint **mais** varreduras heurísticas sobre cada arquivo
de texto do item:

- frases de prompt-injection (`ignore previous instructions`,
  `disregard previous`, aberturas de jailbreak, `do not tell the user`)
- frases de exfiltração de system prompt
- padrões de baixar-e-executar (`curl … | sh`)
- padrões destrutivos de shell (`rm -rf /`, fork bombs)
- strings com formato de segredo — prefixos de token GitHub/Slack,
  chaves `sk-…`, `AKIA…`, marcadores de chave privada, sequências de
  alta entropia, blobs base64 grandes

Achados de segredo imprimem *"possible secret at line N — value
suppressed"*: **o valor encontrado nunca é impresso**, nem em texto nem
em JSON.

`promote --apply` roda G1 na cópia quarentenada e recusa em FAIL.
`gate g1|g2 PATH --apply` grava resultados por item no registro.

### G2 — evidência offline (fundamentação)

O que o item *declara* bate com o que *existe*?

- `files`/`scripts` declarados no frontmatter precisam existir ao lado
  do item (ausente → FAIL)
- referências a paths em code spans são resolvidas relativas ao item
  (ausente → WARN — a skill pode criá-los)
- `commands`/`tools` declarados são procurados no `PATH` (ausente →
  WARN)
- `--packs-dir DIR` verifica que os rubric packs do devin-evals são
  carregáveis — anotado, **não executado** (rodar evals é trabalho do
  devin-evals)

## Limitações honestas

- **Gates heurísticos não são prova.** O G1 pega frases conhecidas e
  *formatos* de token; uma injeção bem redigida ou um formato de segredo
  incomum passa direto, e texto benigno pode gerar falso-positivo. Um
  G1/G2 limpo significa *"nenhum sinal de alerta encontrado"*, não
  *"seguro"*.
- **`.devin/` nunca é escrito.** A quarentena marca + tira snapshot; não
  remove o original. A ativação registra intenção; instalar é manual.
- **Frontmatter não é YAML.** O parser cobre o subconjunto comum
  (escalares, listas, block scalars) e degrada graciosamente no resto.
- **Registro ≠ log de auditoria.** Ele guarda transições e resultados de
  gate para o seu fluxo; não é à prova de adulteração.
- A importação de bundles confia no formato do manifest, não nas
  alegações dele: checksums são verificados, mas os itens chegam em
  quarentena mesmo assim e precisam passar pelos gates para promover.

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m pytest
```

Os testes rodam inteiramente sobre fixtures sintéticos de `.devin/` —
nada real é varrido.

## Quando usar

- Você quer saber quais skills/rules existem entre workspaces e dirs de
  usuário, e se divergiram (`diff`).
- Você vai adotar uma skill vinda de fora e quer um caminho
  quarentena → gate → aprovação em vez de soltá-la direto em `.devin/`.
- Você quer mover itens *revisados* entre máquinas com verificação de
  checksum (`export-bundle` / `import-bundle`).

## Quando NÃO usar

- Você quer um scanner de segurança com garantias — os gates são
  heurísticas, não prova (veja *Limitações honestas*).
- Você quer que a ferramenta modifique `.devin/` — ela é deliberadamente
  read-only lá; só o dir do registro é gravável.
- Você quer executar rubric evals — isso é trabalho do
  [devin-evals](https://github.com/Icaro0310/devin-evals); o G2 só
  verifica que os packs carregam.

## Licença

MIT — veja [LICENSE](LICENSE).
