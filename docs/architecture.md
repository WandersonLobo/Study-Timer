# Arquitetura do StudyTimer

Referência: especificação técnica v1.1 revisada, de 29/10/2026, fornecida em PDF.
O projeto é um aplicativo desktop Windows 10/11 x64, offline e com duas telas.

## Dependências entre camadas

`main.py` é a raiz de composição: resolve caminhos, configura logs, inicializa
SQLite, injeta repositório e relógio nos serviços e recupera a sessão pendente
antes de abrir a janela.

- [application.py](../app/application.py) e [ui/](../app/ui/): navegação e widgets.
  Recebem serviços; não executam SQL nem calculam duração.
- [services/](../app/services/): cronômetro, validação temporal e relatórios.
  Não importam CustomTkinter. O relógio é substituível por `ClockSource`.
- [database/](../app/database/): conexão, transações, consultas e esquema SQLite.
- [models/](../app/models/): dataclasses imutáveis e enumerações compartilhadas,
  com uma classe por arquivo. O `__init__.py` exporta os modelos para os serviços
  e a persistência; dependências internas importam diretamente o módulo da classe.
- [config.py](../app/config.py) e [logging_config.py](../app/logging_config.py):
  configuração local e logs rotativos sem nomes de sessões por padrão.

Não há API, servidor, ORM, autenticação, nuvem ou telemetria.

## Estado desta entrega

Implementado: composição das camadas, navegação inicial, configuração local,
logging, criação do banco, PRAGMAs, esquema, validação transacional básica e
consulta da sessão pendente. O relógio confiável também está implementado, com
âncora única, duração monotônica, validação de ticks e congelamento seguro.
O ciclo de sessões funciona sem interface: início, pausa, retomada, finalização,
heartbeat e recuperação com transações atômicas. A composição recupera a sessão
antes de criar a janela. A interface já executa o ciclo de sessão e salva pausa ao fechar.

Relatórios e Histórico estão implementados. Application agenda ticks e
heartbeats, apresenta erros e recuperação e atualiza o período selecionado com o
snapshot ativo. `recovered` e `idle` são estados visuais, nunca valores persistidos.
O aceite local usa Tk real; os limites estão registrados em acceptance_report.md.

O bloco 1 do plano de tipos/Histórico/temas implementa somente a base de dados
e os serviços: esquema v2, migração v1 → v2, catálogo de tipos e preferência de
aparência. `Session.study_type_id` é opcional, com padrão None. O bloco 2 injeta
os serviços de tipos/preferências na janela, expõe o catálogo no Cronômetro e
aplica Claro/Escuro com preferência salva. O bloco 3 implementa o Histórico por
Dia, Semana e Mês com tipos, gráficos e detalhamento. O bloco 4 acrescenta
regressões de sequências e energia, matriz Tk Claro/Escuro e validação do
executável no fluxo de CI, sem alterar os serviços, o esquema ou o ícone.

## Decisões preservadas da especificação

1. Python **3.12.x**, CustomTkinter e `sqlite3` da biblioteca padrão.
2. Banco em `%LOCALAPPDATA%\StudyTimer\estudos.db`, fora da pasta do programa.
3. `foreign_keys=ON` e `busy_timeout=5000` por conexão; após a revisão de segurança,
   `journal_mode=WAL` e `synchronous=FULL` substituem a decisão DELETE do PDF.
4. Escritas via `BEGIN IMMEDIATE`, validação cruzada antes de COMMIT e rollback.
5. Uma única sessão running/paused e um intervalo aberto por sessão, via índices.
6. Duração por nanossegundos monotônicos; timestamps UTC sintéticos ancorados
   no início. O encerramento não consulta diretamente o relógio civil.
7. Ticks de aproximadamente 250 ms e heartbeat de aproximadamente 5 s.
   Lacuna ou divergência civil acima de 5 s deve pausar no último tick válido.
8. Suspensão Windows deve ser observada por eventos e pelo detector de lacunas.
   `WM_POWERBROADCAST` já está integrado; S3 básico foi confirmado pelo usuário,
   enquanto hibernação e outros cenários físicos ainda exigem aceite.
9. Relatórios usam fronteiras locais meio abertas e somam segundos antes de
   truncar minutos. No Histórico do bloco 3, métricas, gráfico, ranking e sessões
   usam o mesmo período e filtro; a antiga independência dos cartões foi substituída.
10. `ClockSnapshot` identifica o intervalo aberto e substitui seu checkpoint uma
    única vez. Sem snapshot ativo, relatórios usarão `last_seen_at`.
11. Build Windows onedir definido exclusivamente no `.spec`, executado pelo script.

## Relógio confiável — incremento 1

O [ClockService](../app/services/clock_service.py) trabalha com uma fonte
`ClockSource` injetada. Não importa widgets, não agenda callbacks e não grava no
banco. A referência monotônica pode ser qualquer inteiro: somente diferenças
entre leituras são usadas, preservando a precisão em nanossegundos.

| Operação | Comportamento |
| --- | --- |
| `capture_anchor()` | Captura um `ClockReading` sem alterar o estado ou confirmar ticks. |
| `start_interval(interval_id, anchor=None)` | Inicia com duração zero. Reutiliza a âncora fornecida ou captura uma nova; rejeita sobreposição de intervalos. |
| `tick()` | Confirma uma amostra válida e cria um snapshot imutável. Antes do início devolve None; depois de uma pausa devolve o snapshot congelado sem ler a fonte. |
| `pause(reason=USER)` | Congela o último tick aceito sem amostrar o instante atual e conserva o primeiro motivo de pausa. |
| `get_snapshot()` | Apenas consulta o último snapshot, sem fazer a contagem avançar nem ocultar lacunas entre callbacks. |
| `reset()` | Limpa o estado parado; exige pausa prévia se estiver rodando. |

O início armazena `started_at = int(anchor.wall_time_s)` e o instante monotônico
da mesma leitura. A duração aceita é calculada por
`max(0, (mono_atual - mono_inicial) // 1_000_000_000)`. Não há arredondamento por
callback nem soma de segundos truncados a cada tick. O término sintético é sempre
`started_at + elapsed_s`, sem consultar o horário civil para encerrar.

Comparam-se as amostras consecutivas aceitas. Uma lacuna monotônica **maior que**
5 s provoca `TICK_GAP`. Regressão monotônica ou diferença absoluta entre os deltas
civil e monotônico **maior que** 5 s provoca `CLOCK_CHANGE`. Os limites exatos de
5 s são aceitos. O tick rejeitado não avança o snapshot, e a contagem permanece
parada mesmo se a fonte voltar ao normal. Falhas da fonte também congelam antes
de propagar a exceção; o log contém somente motivo e tipo da falha.

### Integração com o serviço de sessão

1. **Implementado:** início e retomada capturam a âncora antes de inserir o intervalo,
   gravam sua parte civil inteira e iniciam o relógio somente após COMMIT com a
   **mesma** âncora. Falhas de escrita não iniciam um novo relógio.
2. **Implementado:** Application usa `after(250)` para chamar `TimerService.tick()`,
   que delega ao relógio. Um callback independente de 5 s chama heartbeat.
3. **Implementado:** a pausa USER valida um último tick antes de congelar. Suspensão,
   falha de escrita e encerramento conservador congelam o último tick confiável
   sem ler a fonte. Se o relógio já detectou anomalia, seu motivo inicial é preservado.
4. **Implementado:** TimerService.tick persiste imediatamente a pausa automática.
   O heartbeat também persiste essa pausa se encontrar o relógio congelado.
   O relógio não altera o banco por conta própria.
5. **Implementado:** retomada exige novo intervalo e nova âncora, preservando a
   sessão. Finalização limpa o relógio somente após confirmar o banco.
6. **Pendente:** relatórios ao vivo receberão snapshot somente enquanto o intervalo
   estiver aberto. Após a pausa persistida, usarão os intervalos fechados e `now=None`.

A UI chama esses comandos pela janela, sem SQL nem acesso à conexão.
O relógio não pode inferir uma UTC correta se o horário civil já estiver errado
no início. A detecção conservadora também pode descartar tempo de estudo durante
um bloqueio prolongado do sistema, conforme a especificação.

### Lacunas do contrato corrigidas neste incremento

- O UML inicial expunha apenas `get_snapshot()`, sem operação para definir a
  âncora, associar o ID do intervalo, validar ticks ou sinalizar a pausa. O ciclo
  de vida agora está explícito no código e no [UML](uml_diagram.md).
- Capturar UTC separadamente no relógio e no futuro comando de inserção poderia
  produzir timestamps diferentes na virada de um segundo. A âncora reutilizável
  evita essa inconsistência na integração transacional.
- A documentação anterior tratava toda a validação temporal como pendente.
  A integração e a persistência foram implementadas nos incrementos 2 a 4.

## Ciclo básico da sessão — incremento 2

O [TimerService](../app/services/timer_service.py) não executa SQL nem mantém uma
cópia mutável da sessão. Consulta o estado persistido e coordena o relógio com os
comandos atômicos de [StudyRepository](../app/database/repository.py).

| Comando | Pré-condição | Escritas na mesma transação |
| --- | --- | --- |
| Iniciar | Sem sessão pendente e com relógio parado; nome normalizado com até 120 caracteres. | Insere sessão paused, insere primeiro intervalo, muda status para running. |
| Pausar | Sessão running e snapshot correspondente ao intervalo aberto. | Confirma last_seen_at e ended_at sintéticos, muda status para paused. |
| Retomar | Sessão paused e relógio parado. | Insere novo intervalo na mesma sessão, muda status para running. |
| Finalizar | Sessão running com snapshot correspondente, ou sessão paused sem snapshot aberto. | Fecha intervalo se necessário e grava finished com finished_at calculado dos intervalos. |

Cada comando abre `BEGIN IMMEDIATE`, verifica seu estado dentro da transação,
valida invariantes antes do COMMIT e reverte tudo em qualquer falha. Não há troca
de nome durante uma sessão nem exclusão dos registros ao finalizar.

Para finalizar, se houve tempo positivo em algum intervalo, `finished_at` é o
maior término confirmado, nunca inferior a `created_at`. Caso contrário, usa
`created_at`. A regra de zero segundos também vale após várias retomadas com
zero segundos. Finalizar paused não consulta o horário civil do clique.

O repositório rejeita snapshots de outro intervalo, âncora diferente, duração
negativa, término diferente de `started_at + elapsed_s` ou término anterior ao
último checkpoint. Uma correção civil durante a pausa pode ancorar o próximo
intervalo antes dos anteriores; seus segundos continuam válidos e `finished_at`
respeita o maior término, sem reescrever o histórico.

Se pausar ou finalizar falhar, o banco sofre rollback e o relógio permanece
congelado com seu snapshot. Repetir o comando usa esse mesmo corte, excluindo
o tempo até a nova tentativa. Em falha de início/retomada, o novo relógio não é
iniciado. O incremento 3 sinaliza essas falhas e permite repetir a escrita sem
retomar a contagem. Diálogos e ações visuais de tentativa pertencem à integração da UI.

Uma sessão running carregada sem um relógio correspondente é rejeitada pelos
comandos de pausa/finalização, exigindo recuperação. O incremento 3 adiciona o
comando explícito de recuperação e sua chamada na abertura; não usa a hora de reabrir.
Sessões paused podem ser retomadas ou finalizadas com novas instâncias dos serviços.

## Persistência e recuperação — incremento 3

### Checkpoint de duração

`TimerService.heartbeat()` consulta o snapshot já aceito por `ClockService.tick()`.
Não lê a fonte de tempo, não confirma ticks e não consulta a hora civil. Enquanto
o relógio roda, `StudyRepository.save_checkpoint(session_id, snapshot)` atualiza
somente `last_seen_at` do intervalo aberto. A mesma validação de identidade,
âncora, duração e não regressão é usada no fechamento. Repetir um checkpoint é
seguro e não altera intervalos anteriores, o início ou o status da sessão.

Sem sessão running, o heartbeat não escreve. Se a sessão está running no banco
mas o relógio correspondente está congelado, o heartbeat fecha o intervalo no
snapshot congelado e grava paused atomicamente. Isso cobre pausas detectadas
pelo relógio e uma nova tentativa após falha de persistência. Não há retomada automática.

Application agenda ticks de aproximadamente 250 ms e heartbeats de 5 s.
O heartbeat não substitui ticks ausentes nem impõe sozinho
uma cadência. `last_seen_at` é um checkpoint de duração da aplicação, distinto
do checkpoint interno do WAL.

### Recuperação na abertura

`main.run_application()` chama `TimerService.recover_pending()` após inicializar
o banco e antes de criar a janela. O serviço exige relógio parado **sem snapshot**,
evitando descartar tempo congelado que ainda pode ser salvo no processo atual.
Não captura hora civil nem reutiliza uma origem monotônica de outro processo.

`StudyRepository.recover_pending()` executa em `BEGIN IMMEDIATE`:

1. Consulta a única sessão pendente dentro da transação.
2. Se running, fecha seu intervalo com `ended_at = last_seen_at` e muda para paused.
3. Valida as invariantes e retorna somente depois do COMMIT.

Sessões já paused, sessões finished e ausência de pendência são preservadas.
Repetir a recuperação não adiciona intervalos nem duração. O retorno é Session
paused ou None; `recovered` é uma apresentação da UI para a pendência na abertura.
Uma nova contagem exige `resume_session()`, com novo intervalo e nova âncora.

Após encerramento abrupto, recupera-se somente o último checkpoint confirmado.
Ticks posteriores ainda em memória são descartados; o período com o programa
fechado nunca é acrescentado. Se não houve heartbeat, o intervalo recuperado tem
zero segundos. Falha na recuperação sofre rollback e impede a abertura da janela;
o tratamento de inicialização mostra uma mensagem estática sem anunciar sucesso.
Na entrega original deste incremento, o esquema permaneceu na versão 1. O bloco 1
do plano posterior introduz a migração explícita para v2, descrita em Banco e
evolução, sem reconstruir os registros existentes.

### Falhas e confirmação de gravação

Todos os comandos de persistência do TimerService propagam `sqlite3.Error` e
congelam o relógio com WRITE_FAILURE, preservando um motivo de pausa anterior.
Isso também cobre falha de leitura durante um comando, antes de sua escrita.
O snapshot confiável permanece em memória para nova tentativa; nenhuma amostra
é aceita durante a espera. Falhas de início/retomada não iniciam novo intervalo
no relógio; falhas de pausa/finalização/heartbeat não confirmam um novo estado.

`persistence_failed` é uma propriedade somente de leitura: fica True após falha
SQLite e só volta a False quando um comando de persistência termina confirmado.
Uma consulta ou heartbeat sem trabalho não a limpa. O banco pode continuar
running por causa do rollback enquanto o relógio está parado; esse status não
autoriza a UI a anunciar contagem ativa ou dados salvos.

O chamador deve tratar a exceção e apresentar mensagem estática, por exemplo:
“Não foi possível salvar. A contagem foi interrompida. Tente novamente.” Só deve
anunciar pausa, finalização ou recuperação salvas após o respectivo retorno.
`persistence_failed=False` não significa que todo tick em memória já foi gravado:
checkpoints são periódicos. Logs registram `PERSISTENCE_FAILED` e o tipo da
exceção, sem seu texto, nomes de sessões, SQL ou caminhos privados.

Repetir pausa/finalização salva o mesmo corte. Repetir heartbeat após uma falha
salva esse corte como paused, sem finalizar nem retomar. Se o processo for fechado
antes de uma tentativa bem-sucedida, prevalece o último checkpoint em disco.

## Integração do Cronômetro — incremento 4

`TimerView` recebe callbacks da `Application`, sem serviços ou SQL. A janela
coordena comandos, navegação, diálogos e dois callbacks `after`: tick a cada
250 ms e heartbeat a cada 5 s. Navegar para Histórico conserva os callbacks.
Não há threads acessando Tk ou a conexão SQLite.

`TimerService.tick()` valida tempo e persiste uma pausa detectada pelo relógio.
`get_elapsed_seconds()` soma os intervalos da sessão pendente, substituindo o
checkpoint aberto pelo snapshot correspondente uma única vez. A tela somente
formata HH:MM:SS; não calcula duração ou consulta a fonte de relógio.

| Estado | Iniciar/Retomar | Pausar | Finalizar | Nome |
| --- | --- | --- | --- | --- |
| idle | Iniciar | Desabilitado | Desabilitado | Editável |
| running | Desabilitado | Habilitado | Habilitado | Bloqueado |
| paused/recovered | Retomar | Desabilitado | Habilitado | Bloqueado |
| Falha com running ainda persistido | Desabilitado | Tentar salvar pausa | Habilitado para repetir | Bloqueado |

O estado visual usa a contagem real, não apenas running no banco. `_failed`
indica operação não confirmada, inclusive falhas de leitura ou da fonte. A janela
congela via `freeze()`, registra apenas código e tipo, e mostra erro estático sem
nome, caminho ou traceback. Não tenta gravar repetidamente a cada callback após
erro: o usuário pode repetir pausa/finalização ou fechamento. Início/retomada
que falham mantêm seu botão disponível conforme o estado persistido. A sinalização
só é removida após comando bem-sucedido; nenhuma falha anuncia dados salvos.

Na abertura, uma pendência recuperada ou já pausada aparece como recovered.
O diálogo oferece Sim (retomar), Não (finalizar) e Cancelar (manter pausada), com
Cancelar como padrão. Não abre novo intervalo antes da escolha explícita.

`WM_DELETE_WINDOW` chama `on_close()`: se running, salva o último tick aceito
como pausa SHUTDOWN, sem capturar tempo não confirmado. Só depois do COMMIT
cancela callbacks e destrói a janela. Se falhar, a janela e o snapshot permanecem
disponíveis; nova tentativa usa o mesmo corte. Sessão já pausada ou ausência de
sessão permitem fechar diretamente. Eventos de energia também estão integrados;
o aceite físico no Windows continua necessário.

## Suspensão e retomada Windows — incremento 5

[WindowsPowerMonitor](../app/windows_power.py) usa `SetWindowSubclass` no HWND
externo do Tk (`GetAncestor(..., GA_ROOT)`) e registra o recebimento com
`RegisterSuspendResumeNotification(..., DEVICE_NOTIFY_WINDOW_HANDLE)`. O callback
ctypes permanece referenciado durante todo o registro; HWND, WPARAM, LPARAM,
LRESULT e identificadores usam tamanhos nativos, preservando a ABI x64.
Registro, mensagens e remoção executam na thread da janela.

`WM_POWERBROADCAST` com PBT_APMSUSPEND (4), PBT_APMRESUMEAUTOMATIC (18),
PBT_APMRESUMESUSPEND (7) ou PBT_APMRESUMECRITICAL (6, compatibilidade) apenas:

1. Marca uma pendência agrupada, inclusive em eventos repetidos.
2. Congela imediatamente o último snapshot aceito com SUSPEND, sem ler a fonte.
3. Retorna TRUE, sem SQL, widgets, diálogo ou espera dentro do callback nativo.

O próximo tick/heartbeat da Application processa essa pendência **antes** de
qualquer amostra. `TimerService.pause_for_power()` persiste paused no snapshot
congelado, somente se a sessão ainda estiver running. Uma ação já enfileirada de
início/retomada/finalização também drena primeiro a pendência, exigindo novo clique
para executar sua ação original. O fechamento drena a pausa antes de sair.
Retomada do Windows sem suspensão recebida também congela antes do próximo tick.
Nenhum evento de energia abre intervalo ou inicia contagem; somente Retomar o faz.

Eventos em idle, paused ou finished não criam intervalos. Notificações de bateria,
AC e outras mensagens seguem para `DefSubclassProc`. Mensagens repetidas são
idempotentes; o primeiro motivo de pausa é preservado. Falhas SQLite mantêm o
snapshot congelado, sinalizam erro e permitem repetir, sem anunciar dados salvos.
Uma notificação sem escrita não limpa `persistence_failed` nem sua indicação visual.

Não se grava dentro de WndProc para evitar bloquear o Windows durante a transição.
Se o processo terminar antes da persistência adiada, a recuperação usa o último
checkpoint confirmado em disco, descartando o restante; não acrescenta tempo
suspenso. `ClockService` mantém o detector de lacunas/divergência como proteção
complementar quando mensagens não forem recebidas.

Antes de destruir a janela, `close()` remove a inscrição e a subclasse. Também
trata WM_NCDESTROY e instalação parcial; falhas de instalação impedem abertura
normal, e falhas de remoção permitem nova tentativa antes de destruir a janela.
Exceções são contidas na fronteira C e os logs usam apenas código/tipo.

Referências primárias: [eventos de energia](https://learn.microsoft.com/en-us/windows/win32/power/wm-powerbroadcast),
[registro de notificações](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registersuspendresumenotification)
e [subclasse na thread da janela](https://learn.microsoft.com/en-us/windows/win32/api/commctrl/nf-commctrl-setwindowsubclass).
Windows não distingue suspensão e hibernação nessas mensagens. Os testes exercitam
mensagens reais em HWND oculto. O usuário confirmou S3 básico com a janela Tk;
hibernação e outras variações físicas continuam pendentes, conforme o
[registro de aceite](acceptance_report.md).

## Relatórios — incremento 6

ReportService resolve o fuso a cada consulta usando `tzlocal.reload_localzone`
e `zoneinfo`, com `tzdata` empacotado para funcionamento offline no Windows.
As versões e hashes estão nos locks; não há consulta de fuso pela rede.
Uma fonte de fuso injetável permite testar mudanças de configuração sem alterar
o Windows. O offset atual não é reutilizado em datas históricas.

Hoje usa [meia-noite, próxima meia-noite); semana usa segunda a próxima segunda;
mês usa dia 1 até dia 1 seguinte. Cada fronteira local é convertida separadamente
para UTC, incluindo DST, meias-noites inexistentes/ambíguas e dias suprimidos.
Interseções são calculadas em segundos UTC. A UI só trunca minutos depois da soma:
35 + 35 segundos são 70 segundos e aparecem como 1 minuto.

`get_report_intervals()` lê candidatos por interseção e identifica o intervalo
aberto do snapshot. O snapshot substitui last_seen_at, nunca é somado a ele;
intervalos fechados ignoram snapshots antigos. Snapshots ativos inconsistentes
ou anteriores ao checkpoint são rejeitados. Consultas não persistem ticks.
Sem snapshot, o intervalo aberto usa last_seen_at.

`get_month_days()` inclui dias vazios com zero, independentemente dos cartões.
`get_day_sessions()` agrega todos os intervalos da mesma sessão no dia e ordena
por duração decrescente, nome e ID. Sessões sem segundos aparecem apenas no dia
de criação; retomadas de zero segundos não criam duplicatas em outros dias.
Os relatórios deste incremento não alteraram o esquema. No bloco 1 posterior,
suas consultas materializam também o vínculo opcional do tipo, sem modificar os
cálculos, os resumos diários ou a interface do Histórico.

## Histórico original — incremento 7

Esta seção registra o contrato da entrega original, substituído na interface
pelo Histórico do bloco 3 descrito adiante. As consultas antigas do serviço
continuam disponíveis para consumidores e regressões existentes.

Application mantém mês exibido e dia selecionado independentes da data de
referência dos cartões. Ao entrar no Histórico e a cada tick visível, consulta
os três relatórios com o mesmo snapshot ativo. TimerService.get_snapshot() é
somente leitura e retorna None após a pausa; não depende de heartbeat para
mostrar tempo em andamento. O Histórico também atualiza a data dos cartões
quando não existe contagem ativa, sem aceitar tempo novo no relógio.

HistoryView recebe resultados e callbacks, sem SQL ou regras temporais. O
contêiner rolável é apresentado com `lift()`, que no CustomTkinter eleva também
o frame externo; `tkraise()` elevaria apenas seu conteúdo interno. O teste Tk
verifica o empilhamento real das duas telas ao navegar em ambas as direções.
O calendário tem 42 posições estáveis, segunda a domingo, navegação mensal,
seleção de dia e botão Hoje. O total mensal soma os segundos do mês exibido;
os cartões usam a data atual. As faixas de intensidade são fixas: zero,
positivo abaixo de 15 min, de 15 a 59 min, de 1 a menos de 2 h e a partir de 2 h.
O dia atual tem contorno azul e o selecionado, dourado. Nomes/meses e estados
vazios usam português. A navegação suporta anos 1 a 9998.

Detalhes exibem HH:MM:SS e nomes quebrados em linhas. A lista começa com 50
sessões e Mostrar mais adiciona outras 50; widgets existentes são reutilizados.
Valores inalterados não reconstroem o calendário nem a lista. Os cartões e
células formatam minutos depois da soma, pelo módulo ui/formatting.py.
Falhas conservam os últimos valores identificados como não atualizados e
interrompem a contagem, sem apresentar uma gravação como confirmada.

## Banco e evolução

O esquema inicial v1 foi reconstruído das seções 11–12 do PDF; o anexo SQL
original não foi disponibilizado. `user_version` é a versão do banco, independente
da versão editorial 1.1. O [schema.sql](../app/database/schema.sql) cria diretamente
v2; [schema_version.py](../app/database/schema_version.py) centraliza a versão
atual e as origens suportadas. Versões desconhecidas são rejeitadas, sem serem
tratadas como corrupção ou rebaixadas automaticamente.

A abertura valida integridade e versão antes de modificar um banco existente.
Para v1, cria backup pela API SQLite em `backups/before-migration/`, validado
como v1, e executa [migrations.py](../app/database/migrations.py) em
`BEGIN IMMEDIATE`. A migração acrescenta tabelas, FK e índice, valida invariantes
e confirma `user_version=2` na mesma transação. Uma falha reverte o DDL e os dados.
Não se usa `executescript()` para contornar essa fronteira transacional.
Somente depois da migração o bootstrap recupera a sessão pendente e abre a UI.

Preservam-se ids, nomes, timestamps, estados, checkpoints, intervalos, índices e
trigger. Registros antigos recebem `study_type_id=NULL`, sem inferir assuntos
pelos nomes. Instalação nova e migração produzem o mesmo esquema lógico.

Backups automáticos, before-migration e before-restore têm retenções independentes
de cinco cópias. A restauração de backup v1 prepara uma cópia pela API SQLite,
migra essa cópia e valida v2 antes de alterar o destino. A origem não é migrada.
Sob o lock exclusivo, o destino válido é preservado antes da restauração pela
API SQLite. Destino corrompido continua sendo recusado, sem reparo automático.
Se o backup selecionado estiver na própria pasta before-restore, a rotação
reserva um lugar para ele entre as cinco cópias; não apaga a origem escolhida.

Depois do COMMIT, voltar ao executável antigo não reverte v2: ele exige v1 e
recusa a abertura. Não existe downgrade automático; uma reversão requer operação
explícita com aplicativo fechado e backup compatível, protegendo os dados atuais.

## Tipos de estudo e preferência — bloco 1

`study_types` guarda id, nome, chave de unicidade, chave de cor e arquivamento.
`StudyType` é imutável e não expõe `name_key`, detalhe de persistência. O serviço
normaliza nomes com NFKC, remove controles, compacta espaços e deriva a chave
com `casefold()`. Nomes têm de 1 a 60 caracteres; Sem tipo é reservado. Acentos
são significativos. A unicidade também abrange arquivados.

`StudyColor` enumera blue, teal, orange, purple, rose, cyan, amber e slate.
A escolha das cores concretas em Claro/Escuro pertence a `app/ui/theme.py`. Não há
importação de CustomTkinter nos modelos ou serviços. Exemplos dos mockups não
são cadastros pré-inseridos no banco.

`StudyTypeService` oferece listagem, criação, edição de nome/cor, arquivamento
e reativação. Não há exclusão física. Renomear ou recolorir preserva id e duração;
arquivar não remove vínculos históricos. Arquivar o tipo da sessão pendente é
rejeitado. Escritas passam por `StudyRepository`, com SQL parametrizado,
validação e retorno somente após COMMIT.

`TimerService.start_session(name, study_type_id=None)` mantém a chamada anterior
compatível. O repositório verifica existência e atividade do tipo dentro da mesma
transação de criação da sessão/intervalo. Uma falha não inicia o relógio. Pausa,
retomada, finalização, checkpoint e recuperação conservam o vínculo. `Session`
materializa esse id também nas consultas de relatórios, sem mudar seus totais.

`app_preferences` tem uma única linha, com id fixo e `appearance_mode` restrito
a light/dark; o padrão persistido é dark. `AppearanceMode` e `PreferencesService`
expõem essa preferência sem aplicar aparência ou acessar widgets. A conexão
permanece encapsulada no repositório. O bloco 2 liga esse serviço ao seletor e
aplica a aparência antes da construção dos widgets.

## Cronômetro, tipos e temas — bloco 2

`main.run_application()` compõe `StudyTypeService` e `PreferencesService` usando
o repositório compartilhado. `Application` recebe os quatro serviços; carrega a
preferência e chama `theme.apply_appearance()` antes de criar a raiz CTk. O
singleton do banco mantém o padrão Escuro. Não há detecção automática do tema
do Windows: a escolha explícita Claro/Escuro é persistida pelo serviço.

`TimerView` mantém um mapa de nomes para ids do catálogo, com Sem tipo associado
a None. A seleção persistida é sempre por id. Tipos arquivados saem das novas
seleções, mas podem ser apresentados se já vinculados à sessão recuperada.
Tipo, descrição e acesso ao cadastro ficam bloqueados em running, paused e
recovered. Finalização confirmada limpa a descrição; falhas preservam os campos.
Não se persiste a última seleção: uma abertura sem pendência começa em Sem tipo.

`StudyTypeDialog` é um CTkToplevel transitório, com grab e foco inicial, lista
rolável de ativos/arquivados e campos de nome/cor. Salvar/arquivar/reativar chamam
serviços; só o retorno confirmado atualiza o catálogo e a seleção. Cancelar não
grava. Erros de validação ficam no formulário e erros de gravação não anunciam
sucesso. Falha ao atualizar a UI depois de um COMMIT informa que o tipo foi
salvo e fecha o diálogo, permitindo recarregar sem criar um registro duplicado.
Fechamento libera o grab e cancela a ativação agendada, inclusive ao fechar a janela.

Trocar a aparência atualiza pares de cor nos widgets existentes; não reconstrói
janela, serviços ou cadeias de after. Preserva sessão, foco, campos e rolagem.
Falha isolada ao gravar a preferência conserva o tema anterior e não altera
`TimerService.persistence_failed` ou o estado de falha do cronômetro. Erros da
sessão continuam usando o congelamento conservador e a tentativa segura atuais.

`theme.py` concentra fundo, superfície, texto, links, borda, seleção, erro e cores
dos tipos. Seus adaptadores de teclado usam o Canvas dos widgets de CustomTkinter
5.2.2, isolando essa dependência: Tab/foco, Enter/Espaço para botões e setas para
seletores. Estados desabilitados não iniciam ações. O corpo do Cronômetro é
rolável e mantém o mínimo 900×600. Nesse incremento, o Histórico conservou
calendário, paginação e contratos de relatório; o bloco 3 substitui sua composição.

Foram removidas as instruções sobre pausa, fechamento, intensidade e atualização
ao vivo. Permanecem rótulos dos dados, estados de operação e mensagens reais de
falha, recuperação e energia. Ícone, esquema v2 e regras temporais não mudaram.

## Histórico por período e tipo — bloco 3

`HistorySelection` é uma dataclass imutável com `period: ReportPeriod`, data de
referência, `type_filter` e identificador opcional de tipo. O filtro usa os
valores all, untyped e type, distinguindo Todos de Sem tipo sem sobrecarregar
None. Em type, o id identifica um cadastro real; nomes e cores não são chaves.
A seleção é estado visual em memória, não uma nova tabela ou preferência salva.

`ReportService.get_period_dates()` determina o início e término local exclusivo:
dia até o dia seguinte, segunda-feira até a próxima segunda, primeiro dia do
mês até o primeiro dia seguinte. `get_period_report(selection, now=None)`
entrega um `PeriodReport` imutável para toda a tela, com fronteiras UTC, total,
média e denominador, buckets, ranking e contribuições de sessões. Nenhuma
consulta grava ticks, checkpoints ou metadados no banco.

Os intervalos e seus tipos são obtidos em lote com LEFT JOIN, incluindo os
registros sem tipo e os cadastros arquivados. Não há uma consulta por barra ou
linha. A contribuição é recortada pelas fronteiras do período; pausas não são
intervalos de estudo. O snapshot confiável substitui o checkpoint aberto uma
única vez, preservando a atualização antes do heartbeat. Snapshots antigos não
estendem intervalos fechados. Zero segundos só produz detalhe no dia de criação,
sem acrescentar uma barra ou um tipo com tempo fictício.

`ReportBucket` representa limites UTC e composição por tipo. No Dia, as faixas
horárias respeitam transições históricas de fuso, inclusive horas repetidas,
suprimidas e mudanças de meia hora. Os limites UTC são ordenados e o detalhe
distingue a ocorrência/offset de uma hora repetida. Semana tem sete buckets
diários; mês tem um por dia civil. Soma de buckets, soma do ranking e total
coincidem em segundos, independentemente da formatação.

`StudyTypeTotal` transporta id, nome, cor, segundos e participação. O ranking
ordena por duração decrescente, nome normalizado e id. Sem tipo é uma categoria
cinza; arquivar não apaga sua contribuição. Percentuais usam os segundos do
filtro, com arredondamento individual de apresentação, sem alterar durações.
Nos gráficos com muitos tipos, os cinco principais e Outros podem resumir a
composição; o ranking continua permitindo selecionar todos os tipos reais.
Outros é somente visual e não é persistido.

No Dia, a métrica principal é o total. Na Semana/Mês, a média divide o total
pelo número de dias civis: sete ou todos os dias do mês em períodos completos;
no período atual, os dias transcorridos até hoje, inclusive. Dias sem estudo
entram no denominador; dias futuros não. Filtrar um tipo não altera essa regra.
O denominador faz parte do resultado e pode ser consultado em dica contextual,
sem instrução permanente. A UI formata os segundos após a soma, com 0min, <1min,
45min ou 2h 30min; os detalhes conservam HH:MM:SS.

`Application` coordena modo, referência, filtro e contexto de retorno. As setas
navegam por uma unidade do modo e preservam o filtro; não permitem períodos
inteiramente futuros. Trocar modo mantém a referência selecionada. Hoje mantém
o modo, volta ao período atual e limpa o filtro/detalhamento. Clicar numa barra
semanal/mensal abre o Dia correspondente, conservando o filtro; Voltar à semana
ou Voltar ao mês restaura o contexto. `DatePicker` oferece seleção compacta da
data sem criar uma terceira tela principal. Os limites de ano seguem 1 a 9998.

`HistoryView` recebe o resultado pronto. `StudyChart` usa Canvas/Tk para converter
segundos em coordenadas, desenhar barras empilhadas e tratar seleção por mouse
ou teclado. Não calcula durações. O eixo se adapta ao maior valor e a composição
do vazio não inventa uma barra mínima. Cores e foco são resolvidos pelo tema;
o detalhe identifica os tipos também por nome. Trocar Claro/Escuro redesenha
os elementos do gráfico sem outra consulta de tempo ou outra janela.

Sessões mostram descrição, tipo, data e somente os segundos do período selecionado.
A data do resumo é a primeira data local de contribuição da sessão naquele
período; intervalos da mesma sessão são reunidos sem incluir as pausas.
A lista mantém lotes de 50 com Mostrar mais. Valores inalterados não recriam
gráfico/listas; ticks mantêm filtro, foco, rolagem e paginação. Renomeação e cor
atualizadas aparecem na próxima consulta. Na virada do dia, a referência de um
período histórico escolhido não salta automaticamente para hoje.

O estado vazio usa Sem estudos neste período. Falhas preservam o último
resultado legível identificado como não atualizado e mantêm o tratamento
conservador da sessão. Não se adicionaram loops concorrentes, threads de Tk,
cache persistente de totais, biblioteca gráfica, esquema ou dependências.

Triggers verificam mudanças de status. A transação do repositório verifica também
o estado final: running exige um intervalo aberto; paused/finished exigem zero.
Adicionar comandos de escrita e consultas à classe de repositório conforme cada
regra for implementada. A conexão não deve escapar para a camada visual.

## Validação e distribuição — bloco 4

A infraestrutura de validação fica fora das camadas de execução. A CI separa
regras e persistência (`quality`), Tk real em cada aparência (`native`) e pacote
Windows (`package`). `packaging/build.ps1` continua sendo a única orquestração
do build onedir de `StudyTimer.spec`; `-DesktopTests` acrescenta os fluxos externos
de mouse/teclado no executável já gerado, sem criar outra entrada de produção.

`packaging/ci_checks.py` verifica Windows/Python 3.12 x64, Tcl/Tk e, na etapa
externa, desktop interativo disponível. Depois da execução, valida os relatórios
JUnit: exige casos, ausência de falhas/skips e a matriz de cenários/temas esperada.
Uma execução local sem opt-in pode pular testes dependentes do ambiente; esse
resultado não satisfaz os gates obrigatórios da CI.

As sequências de sessão usam um modelo independente, relógio injetado e SQLite
temporário real para verificar status, intervalos e conservação dos segundos após
cada ação. Falhas reais de COMMIT verificam repetição no mesmo corte congelado.
Regressões de energia combinam tipo, aparência e tela sem suspender o computador.
O smoke do EXE cobre perfis novos, migração v1 e banco v2 com sessões sintéticas,
recuperação pausada, preferência e preservação dos registros em outra abertura.

Os fluxos externos endereçam somente janelas do PID do executável de teste;
não chamam callbacks de `Application` nem substituem serviços do programa.
Cada processo recebe um `LOCALAPPDATA` temporário. Capturas usam somente sua
janela e dados sintéticos. A exportação de evidências separa o diretório bruto
do público, removendo detalhes de erro e publicando apenas os formatos permitidos.
Esses testes não hibernam o host nem comprovam Windows limpo sem Python.

Resultados e limitações desta execução estão em
[acceptance_report.md](acceptance_report.md). Executar os jobs remotamente e
configurá-los como obrigatórios na proteção da branch são etapas externas ao
código. A instalação limpa, energia física e DPI/hardware continuam exigindo
aceite independente.

## Próximas etapas

1. Concluir os aceites pendentes registrados em [acceptance_report.md](acceptance_report.md).
2. Validar hibernação física, variações de DPI e de hardware; S3 básico já confirmado.
3. Instalar Windows na VM para validar o ZIP sem Python e com rede bloqueada.
4. Incorporar SVGs aprovados e substituir o ícone provisório quando fornecidos.
5. Reexecutar os critérios de atualização e a auditoria de dependências antes de publicar.
