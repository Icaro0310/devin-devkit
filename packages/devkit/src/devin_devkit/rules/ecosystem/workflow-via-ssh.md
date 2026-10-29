# Workflows do GitHub só via SSH

Criar ou editar ficheiros em `.github/workflows/` exige `git push` por
SSH. **Nunca** usar `gh api` contents PUT para workflows:

- O token OAuth não tem o scope `workflow`.
- A API mascara a falha como `404` — parece que o ficheiro ou o branch
  não existe, mas é o scope em falta.
- O push por HTTPS falha também, mas ao menos é rejeitado
  explicitamente.

O caminho correto é sempre commit + `git push` numa remote SSH
(`git@github.com:...`). Se a remote estiver em HTTPS, corrigir a remote
antes — não procurar workaround via API.
