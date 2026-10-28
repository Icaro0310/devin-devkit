# Nunca `git add -A` nem `git add .`

Fazer staging de paths explícitos — `git add <ficheiro>` um a um, ou
por glob restrito e revisto. Lição aprendida: `git add -A`/`git add .`
commita ficheiros scratch esquecidos (notas, dumps, artefactos de
teste) junto com a mudança real.

Antes do commit, correr `git status` para confirmar que só os ficheiros
pretendidos estão staged — e que nada relacionado ficou de fora.
