# Arquitetura do StudyTimer

Referência: especificação técnica v1.1 revisada, de 29/10/2026, fornecida em PDF.
O projeto é um aplicativo desktop Windows 10/11 x64, offline e com duas telas.

## Dependências entre camadas

`main.py` é a raiz de composição: resolve caminhos, configura logs, inicializa
SQLite e injeta repositório e relógio nos serviços antes de abrir a janela.

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
O ciclo básico de sessões também funciona sem interface: início, pausa, retomada
e finalização com transações atômicas. As ações da interface estão desabilitadas.

Heartbeat, recuperação de processo e relatórios ainda levantam `NotImplementedError`.
Não há contagem, gravação de sessões pela UI, recuperação automática ou relatórios
prontos. `recovered` e `idle` são estados visuais, nunca valores persistidos.

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
   A integração `WM_POWERBROADCAST` ainda precisa ser implementada e testada.
9. Relatórios usam fronteiras locais meio abertas e somam segundos antes de
   truncar minutos. O mês exibido é independente dos cartões do período atual.
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
2. **Pendente:** callbacks de aproximadamente 250 ms devem chamar `ClockService.tick()`.
   O heartbeat de 5 s deverá persistir o snapshot já validado; não substituirá os ticks.
3. **Implementado:** a pausa USER valida um último tick antes de congelar. Suspensão,
   falha de escrita e encerramento conservador congelam o último tick confiável
   sem ler a fonte. Se o relógio já detectou anomalia, seu motivo inicial é preservado.
4. **Comando implementado, agendamento pendente:** quando o relógio parar sozinho,
   o chamador deverá acionar `pause_session(clock.pause_reason)` para persistir o
   intervalo e paused. O relógio não altera o banco por conta própria.
5. **Implementado:** retomada exige novo intervalo e nova âncora, preservando a
   sessão. Finalização limpa o relógio somente após confirmar o banco.
6. **Pendente:** relatórios ao vivo receberão snapshot somente enquanto o intervalo
   estiver aberto. Após a pausa persistida, usarão os intervalos fechados e `now=None`.

A UI ainda não chama esses comandos nem agenda os ticks.
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
  Agora distingue o relógio concluído da integração e persistência ainda pendentes.

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
iniciado. Exceções são propagadas; diálogos, política completa de tentativa e
recuperação após reinício continuam para os próximos incrementos.

Uma sessão running carregada sem um relógio correspondente é rejeitada pelos
comandos de pausa/finalização, exigindo recuperação. Não se usa a hora de reabrir
como término nem se encerra silenciosamente no checkpoint neste incremento.
Sessões paused podem ser retomadas ou finalizadas com novas instâncias dos serviços.

## Banco e evolução

O [schema.sql](../app/database/schema.sql) foi reconstruído das seções 11–12 do
PDF; o anexo SQL original não foi disponibilizado. `user_version=1` identifica
este esquema inicial, não a versão editorial 1.1 do documento. Bancos de versões
desconhecidas são rejeitados; migrações futuras precisam ser explícitas.

A revisão de [segurança](security.md) adicionou lock de instância por perfil,
verificação de integridade antes de alterações e backup pela API SQLite ao abrir
um banco existente. Backups são validados e têm retenção de cinco cópias. O banco
original não é reparado automaticamente em caso de corrupção.

Triggers verificam mudanças de status. A transação do repositório verifica também
o estado final: running exige um intervalo aberto; paused/finished exigem zero.
Adicionar comandos de escrita e consultas à classe de repositório conforme cada
regra for implementada. A conexão não deve escapar para a camada visual.

## Próximas etapas

1. Validar as dependências em Python 3.12 x64 e fixar o patch de build aprovado.
2. Implementar heartbeat sobre o relógio e o ciclo de sessões já validados.
3. Implementar recuperação, tratamento de falhas de escrita e eventos Windows.
4. Implementar relatórios e fronteiras locais, incluindo DST e mudança de fuso.
5. Conectar as duas telas, estados visuais, modais e calendário mensal.
6. Incorporar SVGs aprovados e substituir o ícone provisório.
7. Executar a matriz de aceite, build e teste em Windows sem Python instalado.
