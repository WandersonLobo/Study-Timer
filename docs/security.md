# Segurança e privacidade

Revisão inicial em 29/10/2026; persistência e recuperação atualizadas em 30/10/2026.
O app continua local, sem login, sincronização ou exportação CSV. O cronômetro e
o tratamento de falhas funcionam pelos serviços e pela tela Cronômetro.
Erros em callbacks usam mensagens estáticas e logs sem detalhes privados.
O fechamento mantém a janela aberta quando a pausa não pode ser confirmada.

## Correções aplicadas

- Git ignora bancos/sidecars SQLite, cópias de corrupção, backups, logs, CSVs,
  ambientes e pacotes. A inspeção dos nomes de arquivos em todos os commits
  disponíveis não encontrou bancos, logs ou exportações pessoais. Não foi
  necessário reescrever histórico.
- Inicialização exige uma instância por perfil usando lock de byte Windows.
  O sistema libera o handle mesmo se o processo terminar abruptamente.
- Bancos existentes passam por `integrity_check`, `foreign_key_check` e
  `user_version` antes de alterações. Versões desconhecidas são rejeitadas.
  Corrupção preserva cópias `.corrupt` do banco e dos sidecars existentes;
  nenhum reparo automático ou descarte do original é executado.
- Esta revisão substitui `journal_mode=DELETE` do PDF por **WAL + synchronous=FULL**.
  Os checkpoints de duração do cronômetro continuam sendo uma regra separada.
- A abertura de um banco existente cria um backup validado pela API SQLite,
  mantendo as cinco cópias mais recentes na pasta privada `backups/`.
  Falha ao validar ou criar o backup impede a abertura normal.
- A restauração disponível em `restore_backup()` valida a origem, obtém o lock
  exclusivo e preserva um backup do destino antes de restaurar pela API SQLite.
  Essas cópias ficam em `backups/before-restore/`, com retenção própria de cinco,
  para não excluir o arquivo escolhido durante a restauração.
  Ainda não existe botão de backup/restauração na UI.
- O nome é limpo de caracteres de controle e espaços nas pontas; vazio vira
  “Estudo livre”. O limite permanece **120 caracteres**, como definido no PDF.
  SQL recebe entradas por parâmetros; teste estático rejeita SQL dinâmico no app.
- Falhas de inicialização mostram texto estático sem caminhos ou tracebacks.
  Logs usam códigos e tipos de exceção, sem interpolar nome ou conteúdo de sessão.
  A rotação permanece em 1 MiB com três arquivos anteriores.
- Heartbeat grava apenas snapshots validados, com rollback em falhas. Erros SQLite
  congelam a contagem, propagam e mantêm `persistence_failed=True` até um comando
  confirmado; não se anuncia sucesso por apenas conservar dados em memória.
  O log registra `PERSISTENCE_FAILED` e o tipo, sem detalhes privados da exceção.
- Antes de criar a janela, a recuperação fecha a sessão interrompida exatamente
  em `last_seen_at` e mantém paused, sem acrescentar o tempo com o app fechado.
  Falha na recuperação impede a abertura normal. Não há reparo destrutivo nem
  retomada automática; ticks ainda não confirmados podem ser perdidos em um crash.
- O build usa uma venv nova e uma cópia de fontes em pasta neutra, fora do perfil
  e do OneDrive. O pacote e o ZIP extraído são inspecionados para bloquear bancos,
  logs, backups, CSVs, links simbólicos e caminhos privados detectáveis.
  Um candidato só é copiado para a saída final depois dessas verificações.
- Locks de dependências contêm versões exatas e SHA-256 das wheels do PyPI oficial
  para CPython 3.12/Windows x64. Build e CI exigem `--require-hashes` e `pip check`.
  As actions usadas no CI também são fixadas por hash de commit.

## Auditoria das dependências

`pip-audit 2.10.1` encontrou avisos nas versões iniciais de `pytest` e `setuptools`.
Foram atualizadas para `pytest==9.0.3` e `setuptools==84.1.0`, incluindo a dependência
`pygments` do novo pytest. Nova consulta dos pins completos não encontrou
vulnerabilidades conhecidas. Isso não equivale a garantia de ausência de falhas.

Reexecutar a auditoria com uma instalação confiável de `pip-audit`, após qualquer
atualização de dependências e antes de distribuir:

```powershell
pip-audit --no-deps --disable-pip -r requirements-dev.txt
```

Os arquivos `.in` são a fonte dos pins. Para atualizar os hashes, baixar as wheels
em um diretório vazio e gerar novamente os arquivos `.txt`:

```powershell
python -m pip --isolated download --index-url https://pypi.org/simple --only-binary=:all: --python-version 3.12 --platform win_amd64 --implementation cp --abi cp312 -r requirements-dev.in -d C:\StudyTimerBuild\wheels
python packaging/lock_dependencies.py C:\StudyTimerBuild\wheels
```

Não substituir hashes para contornar um erro de instalação. Revisar a mudança,
auditar versões, verificar resolução completa e executar testes antes do build.

## Proteção dos arquivos locais

SQLite, backups e cópias `.corrupt` **não são criptografados**. As permissões
herdadas do perfil não protegem contra alguém que acesse a mesma conta ou uma
cópia do banco. Use bloqueio por senha do Windows e criptografia de dispositivo
ou BitLocker quando disponível. Mantenha backups em armazenamento protegido;
não publique bancos, logs ou capturas com dados pessoais nem os envie por
mensageiro ou pasta compartilhada.

Com WAL, não copie somente `estudos.db` com o app aberto: dados confirmados podem
estar em `-wal`. Use a API de backup implementada. Para suporte manual, feche
o app normalmente antes de copiar ou substituir arquivos. Nunca remova sidecars
para tentar corrigir um banco. Um destino corrompido exige análise manual após
preservar todos os arquivos; a função de restauração o rejeita por segurança.

## Limites que ainda exigem aceite

- Interface completa e executável com firewall bloqueando a rede; o teste atual
  cobre apenas inicialização da infraestrutura com sockets indisponíveis.
- Build real com Tcl/Tk, revisão dos metadados e teste em Windows sem Python.
  O scanner verifica bytes dos arquivos extraídos, sem prometer encontrar todos
  os formatos de metadados comprimidos ou codificados.
- Assinatura de código é futura. O SHA-256 confirma a cópia quando comparado a
  um hash obtido de fonte confiável; sozinho não identifica o autor.
- CSV e nuvem permanecem fora do escopo. CSV futuro deve neutralizar fórmulas;
  sincronização exigirá nova avaliação de privacidade e segurança.

Referências: [backup SQLite no Python](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup),
[PRAGMAs e synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous),
[instalações com hash no pip](https://pip.pypa.io/en/stable/topics/secure-installs/).
