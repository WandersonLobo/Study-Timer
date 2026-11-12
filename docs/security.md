# Segurança e privacidade

Revisão inicial em 29/10/2026; persistência e recuperação atualizadas em 30/10/2026.
Migração de esquema e serviços do bloco 1 atualizados em 03/11/2026.
Interface de tipos e aparência do bloco 2 atualizada em 04/11/2026.
Histórico por período e filtros do bloco 3 atualizado em 04/11/2026.
Infraestrutura de validação e evidências do bloco 4 atualizada em 04/11/2026.
O app continua local, sem login, sincronização ou exportação CSV. O cronômetro e
o tratamento de falhas funcionam pelos serviços e pela tela Cronômetro.
Erros em callbacks usam mensagens estáticas e logs sem detalhes privados.
O fechamento mantém a janela aberta quando a pausa não pode ser confirmada.
Eventos nativos de energia congelam antes da próxima amostra; a gravação usa a
fila da UI. Retomar o Windows não retoma a sessão. O callback não executa SQL,
não exibe diálogos e não deixa exceções atravessarem a fronteira nativa.

## Correções aplicadas

- Bloco 4: cada execução usa perfis temporários com dados sintéticos. O smoke
  valida migração v1 e recuperação sem consultar o perfil pessoal. Fluxos
  externos enviam mouse/teclado somente à janela do PID criado pelo teste;
  capturas são limitadas àquela janela, sem capturar o desktop inteiro.
  As regressões de energia não suspendem nem hibernam o computador executor.
- Relatórios brutos e dados temporários ficam fora dos artefatos públicos.
  `packaging/ci_checks.py export` prepara outra pasta com JUnit sanitizado,
  metadados permitidos e PNG sintético. Não publica mensagens, tracebacks,
  stdout/stderr, propriedades brutas de testes, bancos, sidecars, backups ou
  logs. A CI anexa somente essa saída preparada e o pacote já inspecionado.
  O build continua único, com verificação do ZIP extraído antes de copiar a
  entrega final. Esquema, dependências e ícone não mudam neste bloco.
- Pré-condições e verificação de JUnit fazem falta de ambiente, coleta vazia,
  skips e matrizes incompletas falharem nas etapas obrigatórias. A execução do
  fluxo remoto e os checks obrigatórios na proteção da branch ainda precisam
  de evidência; configurar arquivos locais não comprova essas duas medidas.

- Bloco 3: filtros e seleção de data são estado visual em memória. Consultas
  parametrizadas recortam os intervalos e incluem o catálogo por LEFT JOIN,
  sem modificar registros, calcular tempo na UI ou gravar totais derivados.
  Tipos arquivados e Sem tipo permanecem nos resultados históricos. O gráfico
  Canvas é local, usa os segundos entregues pelo serviço e não carrega conteúdo
  remoto. Dicas e detalhes exibem dados na própria janela, sem acrescentá-los
  aos logs. Falhas conservam a identificação de resultado não atualizado.
- Períodos, buckets e percentuais usam somente o snapshot confiável e os
  intervalos persistidos. Consultar ou filtrar não aceita tempo novo, reabre
  sessão ou altera o motivo de pausa. O esquema continua v2, com backups,
  integridade e migração existentes preservados. Não houve alteração de
  dependências, ícone, build ou CI neste bloco.

- Bloco 2: diálogos de tipos chamam os serviços existentes, sem SQL na UI nem
  alteração de durações. Tipo/descrição são bloqueados em uma sessão pendente.
  Validação mostra mensagens do domínio sem nomes interpolados; falhas inesperadas
  mostram texto estático e registram somente código/tipo. Uma falha de interface
  após COMMIT é distinguida de falha de gravação para evitar duplicação na tentativa.
- A preferência de aparência continua no banco local v2, sem arquivo de
  configuração adicional ou serviço externo. Trocar o tema não limpa uma falha
  de persistência da sessão nem reabre um intervalo. Não houve mudanças em
  dependências, ícone, build ou CI neste bloco.

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
- O esquema atual é v2. A versão v1 é aceita somente pelos caminhos explícitos
  de preparação/migração e restauração; a validação normal exige a versão atual.
  A migração cria backup v1 validado em `backups/before-migration/` antes do DDL,
  com retenção própria de cinco. DDL, validação e mudança de versão usam uma
  transação com rollback. Nenhuma sessão ou intervalo é recriado.
- A restauração disponível em `restore_backup()` valida a origem, obtém o lock
  exclusivo e preserva um backup do destino antes de restaurar pela API SQLite.
  Essas cópias ficam em `backups/before-restore/`, com retenção própria de cinco,
  para não interferir nas demais rotações. Se a origem escolhida estiver nessa
  própria pasta, ela ocupa um lugar protegido na retenção: a nova cópia do
  destino não pode apagá-la ao remover backups antigos.
  Ainda não existe botão de backup/restauração na UI.
- Para restaurar uma origem v1, a preparação migra e valida uma cópia temporária
  SQLite antes de alterar o destino. O backup de origem permanece intacto.
  Uma falha nessa preparação conserva o destino; um destino corrompido continua
  recusado. Não existe downgrade automático nem substituição destrutiva para
  acomodar versões desconhecidas. Executáveis v1 não abrem o banco já migrado.
- O nome é limpo de caracteres de controle e espaços nas pontas; vazio vira
  “Estudo livre”. O limite permanece **120 caracteres**, como definido no PDF.
  SQL recebe entradas por parâmetros; teste estático rejeita SQL dinâmico no app.
- Os nomes dos tipos também são dados privados e não entram nos logs. São
  normalizados com NFKC, remoção de controles, compactação de espaços e chave
  `casefold()`, com limite de 60 caracteres. Chaves de cor e aparência pertencem
  a enumerações restritas. Tipos e preferência são gravados com parâmetros e
  transações, preservando as mesmas fronteiras entre serviços, banco e UI.
- Falhas de inicialização mostram texto estático sem caminhos ou tracebacks.
  Logs usam códigos e tipos de exceção, sem interpolar nome ou conteúdo de sessão.
  A rotação permanece em 1 MiB com três arquivos anteriores.
- O ponto de recuperação local contém o identificador do intervalo, a âncora e a
  duração validada. O worker sincroniza o temporário antes da substituição. A
  abertura verifica a correspondência com o intervalo aberto antes de incorporar
  o ponto. Os arquivos `*.pending` ficam no perfil privado e são excluídos do pacote.
- Erros SQLite
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

### Validação do pacote MVP

Os novos relatórios usam tzlocal e tzdata com pins e hashes. O build revelou
incompatibilidade entre o altgraph antigo e setuptools sem pkg_resources;
PyInstaller, hooks e altgraph foram atualizados para 6.22.3, 2026.9 e 0.17.5,
respectivamente, preservando setuptools 84.1.0. Os 20 pins foram consultados nos
metadados de vulnerabilidades do PyPI sem avisos informados nessa consulta;
isso não substitui auditorias futuras nem garante ausência de vulnerabilidades.

O scanner reconhece somente a expressão completa de exemplo público de
`ntpath.splitroot` incluída no CPython. Não há exceção geral para DLLs, arquivos,
nomes de usuário ou diretórios. Perfis fornecidos explicitamente continuam
bloqueados mesmo se coincidirem com esse exemplo. Testes cobrem texto UTF-8,
UTF-16 e fronteiras de blocos, além de caminhos reais ao lado do exemplo.

Inicialização sem console fornece stdout/stderr nulos quando ausentes, permitindo
fallback de bibliotecas sem gravar suas mensagens potencialmente privadas.
Erros de startup registram tipo, módulo, função e linha, sem mensagem da exceção,
traceback completo ou caminhos. `APPLICATION_READY` só é emitido após construir
a interface; o smoke test exige esse marcador e rejeita STARTUP_FAILED.

### Inspeção preliminar de logs e artefatos — antes do build MVP, 30/10/2026

- Os logs disponíveis dos perfis normal e de aceite apresentaram somente
  timestamps, códigos e motivos de pausa. Não foram encontrados caminhos de
  perfil, nome da conta, e-mails, IPs ou tracebacks nos logs do aplicativo e
  nos arquivos de saída da execução verificados.
- Os sete logs do instalador em `.cache/python-setup/` contêm caminhos privados,
  inclusive nos arquivos UTF-16. São diagnósticos locais do instalador, não logs
  do aplicativo. Não devem ser publicados nem enviados sem redação dos dados.
- Os 23 logs encontrados dentro do projeto no momento da inspeção estavam
  ignorados pelo Git. O índice e os nomes de arquivos do histórico local
  disponível não apresentaram logs, bancos ou pacotes de distribuição privados.
- Não havia saída em dist/build, diretório padrão de build neutro ou pacote
  StudyTimer ZIP nas localizações verificadas do projeto e Downloads. Assim,
  nenhum pacote real pôde ter seu conteúdo certificado nesta inspeção.
- Os 19 testes de segurança passaram, incluindo rejeição de dados privados no
  pacote. Isso verifica a proteção implementada, não um executável ainda não gerado.

Não compacte o diretório de trabalho inteiro: `.gitignore` não exclui arquivos
de um ZIP manual. Distribua somente a saída validada de `packaging/build.ps1`.
A inspeção local não comprova ausência de envio anterior, cópias em outros locais,
sincronização, anexos ou artefatos remotos de CI; esses destinos não foram auditados.

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

- Windows limpo sem Python e com rede desconectada: adiado pelo usuário até
  existir Windows na VM. O build real, o smoke, o ciclo e o Histórico foram
  aprovados localmente; o EXE também funcionou em AppContainer sem capabilities
  de rede. Esses resultados não substituem o ambiente limpo.
- A inspeção do pacote final incluiu arquivos extraídos, módulos PYZ e `.pyc`
  descomprimidos, sem caminhos privados detectados. Não se promete encontrar
  todos os formatos possíveis de metadados comprimidos ou codificados.
- Hibernação física e a matriz completa de DPI/hardware permanecem pendentes;
  resultados e limites estão em [acceptance_report.md](acceptance_report.md).
- O job externo exige desktop Windows interativo e desbloqueado. Um runner
  dedicado pode ser escolhido por `STUDYTIMER_DESKTOP_RUNNER`; permita seu uso
  somente por código confiável, pois executa o pacote e gera entradas de usuário.
  A criação dos jobs não comprova execução remota ou proteção efetiva da branch.
- Assinatura de código é futura. O SHA-256 confirma a cópia quando comparado a
  um hash obtido de fonte confiável; sozinho não identifica o autor.
- CSV e nuvem permanecem fora do escopo. CSV futuro deve neutralizar fórmulas;
  sincronização exigirá nova avaliação de privacidade e segurança.

Referências: [backup SQLite no Python](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup),
[PRAGMAs e synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous),
[instalações com hash no pip](https://pip.pypa.io/en/stable/topics/secure-installs/).
