# Plano de validação

Os arquivos de teste seguem a estrutura da seção 10 do PDF. Arquivos reservados
apenas com docstring não representam testes executados nem requisitos aprovados.

| Arquivo | Cobertura | Situação atual |
| --- | --- | --- |
| `test_bootstrap.py` | Caminhos, logs e inicialização (parte CT-11/27) | Base e recuperação antes de criar a janela |
| `test_repository.py` | PRAGMAs, índices, checks, transações (parte CT-09/15) | Testes da base |
| `test_database_safety.py` | Corrupção, WAL, backups e restauração | Testes de segurança |
| `test_security.py` | Nome, SQL, privacidade, pacote, lock e infraestrutura offline | Testes de segurança |
| `test_clock.py` | Parte de CT-03/12/13/16: monotônico, lacunas, correção civil e snapshots | Relógio confiável com fonte simulada |
| `test_ui_states.py` | Parte de CT-01/03/16/17/26 | Callbacks reais, widgets simulados e SQLite temporário |
| `test_windows_power.py` | Parte de CT-13/16/18 | Energia simulada, SQLite real e mensagens em HWND nativo oculto |
| `test_timer.py` | CT-02/03, parte de CT-04/09/12/13/15/18 | Ciclo de sessão sem interface e rollback real |
| `test_reports.py` | CT-05/06/07/14/25 | Fronteiras, fusos, DST, snapshots e 1.000 sessões |
| `test_history.py` | CT-05/07/14/17/25 | Calendário, cartões independentes, detalhes e atualização ao vivo |
| `test_native_ui.py` | Aceite local do MVP | Quatro cenários opt-in com Tk real, isolados por processo |
| `test_recovery.py` | Parte de CT-04/08/18/19 | Heartbeat, falhas SQLite e recuperação em novo processo |
| `test_build_smoke.py` | Conteúdo e abertura do onedir (parte CT-23) | Condicional ao build |

Executar com o ambiente Python 3.12 ativado:

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

O teste de build é pulado quando `STUDYTIMER_BUILD_DIR` não está definido.
O script de build define essa variável após gerar o executável e testa a abertura
por alguns segundos. Esse teste não comprova todas as interações da interface.

Antes da entrega do MVP, executar CT-01 a CT-27 e registrar ambiente, resultado e
evidência. Incluir: viradas de dia/semana/mês, DST, relógio para frente/trás,
suspend/hibernate real, falha de escrita, recuperação de processo, backup/restauro,
janela 900×600 e consulta de pelo menos 1.000 sessões em até 2 s no ambiente medido.
CT-20 exige Windows limpo sem Python; a abertura local do pacote não o substitui.

## Ambiente desta criação

Esta seção e os incrementos 1 a 5 preservam o histórico das validações iniciais.
O ambiente completo preparado posteriormente e os incrementos 6 a 8 atualizam
esses limites; consulte [os resultados atuais](acceptance_report.md).

Para verificar inicialmente esta entrega, foi preparado um runtime
temporário Python 3.12.10 x64, com as dependências fixadas, fora do repositório.
Esse runtime embutido não inclui Tcl/Tk e não substitui a instalação de
desenvolvimento descrita no README.

Validação inicial da base em 29/10/2026: 11 testes aprovados e um smoke test de build
pulado por ausência de pacote gerado. A revisão de segurança acrescentou testes
de corrupção, backup, restauração, SQL e instância única. Ruff (lint e formatação)
e mypy são executados na mesma linha Python 3.12. Interface e build Windows não
foram validados.
Dependências fixadas continuam sujeitas ao aceite do build completo.
Não se declara suporte ao Python 3.13 ou superior.

## Incremento 1 — relógio confiável

[test_clock.py](../tests/test_clock.py) usa uma fonte simulada, sem `sleep`, sem
SQLite e sem widgets. Controla separadamente nanossegundos monotônicos e horário
civil. A cobertura inclui:

- Âncora UTC única, reutilização da amostra na futura transação e rejeição de
  início concorrente ou limpeza de um relógio em execução.
- Frações acumuladas antes do truncamento, milhares de callbacks irregulares e
  origens monotônicas grandes, nulas ou negativas sem perda da diferença inteira.
- Lacuna de exatamente 5 s aceita; acima de 5 s congela o último snapshot.
- Alteração civil para frente/trás, fronteira exata de 5 s, ajustes graduais e
  regressão monotônica sem duração negativa ou alteração da âncora.
- Pausa que não lê a fonte nem retoma automaticamente; um novo intervalo começa
  em zero e não contabiliza o período pausado.
- Getters e leituras de diagnóstico que não confirmam ticks nem ocultam lacunas.
- Falha da fonte e âncora não finita, preservação do último snapshot e logs sem
  texto potencialmente privado da exceção.

Para executar apenas esse incremento: `python -m pytest tests/test_clock.py`.
A suspensão simulada valida o detector conservador; o incremento 5 integra os
eventos Windows. CT-13 ainda exige teste de suspend/hibernate físico. O incremento 2 cobre a mudança de
status no banco, e o incremento 3 cobre heartbeat e recuperação de processo.

## Incremento 2 — ciclo básico de sessão

[test_timer.py](../tests/test_timer.py) integra os serviços com SQLite temporário
real e reutiliza a fonte simulada de relógio. Não carrega widgets nem consulta o
banco pessoal. Cobre:

- Início, pausa, retomada e finalização; mesma sessão e novo intervalo em cada retomada.
- Nome padrão, normalização, limite de 120 caracteres e nome contendo sintaxe SQL.
- Exclusão do tempo pausado, truncamento por intervalo e histórico preservado.
- Sessão de zero segundos, inclusive após uma retomada horas depois.
- Finalização paused sem ler a fonte e maior término após correção civil entre intervalos.
- Sessão única em running/paused, inclusive com duas conexões ao mesmo arquivo.
- Estados inválidos, relógio ausente após reinício e falha da fonte ao retomar.
- Rollback de sessão/intervalo por triggers de falha no meio da operação.
- Negação real de COMMIT pela API `set_authorizer` do SQLite nos quatro comandos;
  banco intacto, relógio seguro e repetição sem contabilizar o tempo de espera.
- Reabertura do arquivo com novas instâncias dos serviços para retomar uma sessão paused.

[test_repository.py](../tests/test_repository.py) também verifica snapshots
inconsistentes ou anteriores ao checkpoint e o contrato de finalização para cada estado.
Executar: `python -m pytest tests/test_timer.py tests/test_repository.py`.

Os testes do incremento 2 não cobrem heartbeat ou recuperação de sessão running;
esses cenários são cobertos pelo incremento 3. O incremento 4 testa callbacks
de fechamento e modais; o aceite visual e eventos reais de energia seguem pendentes.

## Incremento 3 — persistência e recuperação

[test_recovery.py](../tests/test_recovery.py) usa SQLite temporário real e relógio
simulado. Cobre:

- Heartbeat sem amostrar relógios: persiste só o último tick aceito, sem arredondar
  frações para cima nem confirmar tempo posterior; repetir não soma duração.
- Heartbeat sem sessão running não escreve; heartbeat com relógio congelado
  persiste o corte seguro e paused, inclusive após lacuna ou correção civil.
- Falhas reais de COMMIT (`set_authorizer`), banco somente leitura (`query_only`),
  bloqueio por segunda conexão e `SQLITE_FULL` (limite de páginas e escrita em trigger).
  O teste de bloqueio usa timeout zero para falhar sem espera real.
- Rollback, snapshot e primeiro motivo preservados; `persistence_failed=True`
  até um comando confirmado. Leituras e heartbeat sem trabalho não apagam o erro.
- Nova tentativa de heartbeat salva paused no mesmo corte, excluindo a espera;
  retomar exige comando explícito e cria outro intervalo.
- Falhas de leitura durante heartbeat também interrompem a contagem; logs não
  incluem nomes de sessões nem texto privado da exceção.
- Reabertura do arquivo com novas instâncias: recuperação no checkpoint, sem
  consultar a fonte e sem incluir um dia com o programa fechado; zero segundos
  quando não houve heartbeat. Recuperação idempotente, histórico preservado,
  rollback de recuperação e proteção do snapshot do processo atual.
- Dois processos reais: o primeiro termina com `os._exit()` sem fechar a conexão,
  com WAL ainda presente, tanto após ticks não salvos como imediatamente antes
  do COMMIT de um novo checkpoint. O segundo recupera 5 segundos, com origem
  monotônica nova e relógio civil dois dias adiante, e termina com 7 após retomar
  por mais 2 segundos. Não há `sleep` nem dependência do relógio real.

[test_repository.py](../tests/test_repository.py) valida checkpoints repetidos,
identidade e limites dos snapshots e preservação dos intervalos anteriores.
[test_timer.py](../tests/test_timer.py) também verifica a sinalização de erro nos
quatro comandos do ciclo. [test_bootstrap.py](../tests/test_bootstrap.py) substitui
somente a janela para verificar que a composição recupera antes de criá-la.

```powershell
python -m pytest tests/test_clock.py tests/test_timer.py tests/test_repository.py tests/test_recovery.py tests/test_bootstrap.py
```

Os testes verificam a fronteira de persistência e a saída abrupta do processo;
não simulam queda física de energia nem defeito do dispositivo de armazenamento.
O incremento 4 integra callbacks e diálogos; sua validação visual nativa e os
eventos Windows continuam pendentes. O build depende da geração do pacote.

Validação do incremento em 30/10/2026, no runtime temporário Python 3.12.10 x64:
`python -m pytest --basetemp .pytest_cache/persistence-final` aprovou 153 testes,
com um smoke test pulado por ausência de build. `python -m ruff check .`,
`python -m ruff format --check .`, `python -m mypy` e `git diff --check` passaram.
`python -m pip check` não pôde executar: esse runtime não contém o módulo pip.
Dependências e locks não foram alterados nesta etapa.

## Incremento 4 — interface do cronômetro

`test_ui_states.py` carrega Application e TimerView reais com widgets, diálogos
e fila after simulados, preservando TimerService, ClockService e SQLite reais.
Não usa banco pessoal, `sleep` ou relógio real. Executar:

```powershell
python -m pytest tests/test_ui_states.py tests/test_timer.py tests/test_recovery.py
```

Cobre ciclo pelos callbacks dos botões, 250 ms/5 s, estado e bloqueio do nome,
tempo acumulado após retomada, navegação, pausa por lacuna, escolhas do diálogo
de recuperação, erros privados, falhas de início/retomada/pausa/finalização/
heartbeat/fechamento, repetição sem tempo extra, falha da fonte e cancelamento dos
callbacks ao fechar. O teste de recuperação usa a mesma composição de serviço
recuperado que a entrada real.

Esses testes não comprovam renderização, foco, modalidade nativa, escala DPI ou
janela mínima. No Windows com Python 3.12 x64 e Tcl/Tk, validar manualmente:

1. Iniciar, pausar, aguardar, retomar e finalizar; conferir total e nome bloqueado.
2. Navegar para Histórico durante contagem e voltar sem perder estado.
3. Fechar durante contagem e reabrir; testar as três escolhas da recuperação.
4. Confirmar nome inválido, falhas de gravação e nova tentativa sem anúncio de sucesso.
5. Conferir legibilidade, diálogos e botões em 900×600 e escala do Windows.

O runtime temporário de validação continua sem Tcl/Tk e pip: não permite aceite
visual nem `pip check`. Não foram alteradas dependências ou locks.

Validação automatizada do incremento: Python 3.12.10 x64,
`python -m pytest --basetemp .pytest_cache/ui-final`: 169 aprovados e um smoke test
de build pulado por ausência de pacote. `python -m ruff check .`,
`python -m ruff format --check .`, `python -m mypy` e `git diff --check` passaram.

## Incremento 5 — energia Windows

`python -m pytest tests/test_windows_power.py tests/test_ui_states.py tests/test_clock.py`
cobre suspensão, três variantes de retomada, eventos duplicados/irrelevantes,
idle/paused/finished, prioridade sobre ação enfileirada, falha de COMMIT e repetição
com corte preservado. O relógio simulado avança uma hora com e sem avanço monotônico;
nenhum segundo suspenso entra no total. SQL e UI só são acionados após o callback.

Um teste Windows cria um HWND STATIC oculto e usa SetWindowSubclass,
RegisterSuspendResumeNotification e SendMessageW reais. Verifica retorno TRUE,
encaminhamento de mensagens irrelevantes, callback vivo após GC, remoção e ausência
de chamadas após close. Outros testes verificam HWND inválido, instalação parcial,
contenção de exceções na fronteira C e repetição da limpeza após erro.
Nenhum teste manda o computador suspender ou hibernar.

Aceite físico ainda pendente: iniciar e anotar o total, suspender pelo Windows,
aguardar e retomar; conferir paused, total estável e Retomar explícito. Repetir
com hibernação se habilitada, com janela minimizada e na tela Histórico. Verificar
falha de escrita durante o evento e fechamento após acordar. Isso também valida
o HWND externo real do Tk e a entrega de eventos pelo hardware/Windows.

Validação automatizada em Python 3.12.10 x64:
`python -m pytest --basetemp .pytest_cache/power-full` aprovou 189 testes,
com um smoke test pulado por ausência de build. `python -m ruff check .`,
`python -m ruff format --check .`, `python -m mypy` e `git diff --check` passaram.
O runtime utilizado nessa validação não incluía Tcl/Tk e pip; não foi possível realizar aceite visual,
suspend/hibernate físico ou `pip check`. Não houve atualização de dependências.

## Ambiente completo preparado para o aceite físico

Em 30/10/2026 foi instalado Python 3.12.10 x64 completo no perfil do usuário,
com assinatura Authenticode válida da Python Software Foundation. A `.venv`
agora usa essa instalação, com pip 25.0.1 e Tcl/Tk 8.6 (Tcl 8.6.15).
As dependências foram instaladas do PyPI com os hashes de `requirements-dev.txt`.
`python -m pip check` passou, assim como Ruff, formatação e mypy. A suíte
`python -m pytest --basetemp .pytest_cache/python312-tk` aprovou 189 testes,
com um smoke test de build pulado por ausência de pacote.

A janela nativa abriu com o monitor de energia instalado e sem erros de
inicialização registrados. O perfil exclusivo de aceite é
`%LOCALAPPDATA%\StudyTimer-Acceptance\StudyTimer\`, sem uso do banco pessoal.
Os estados de energia devem ser consultados localmente com `powercfg /a`, sem
publicar o inventário da máquina. Após reabrir, a captura da
janela Tk real confirmou a tela Cronômetro em Pronto, com 00:00:00 e sem diálogo
de erro. Isso confirma a abertura visual inicial; não constitui aceite de todo
o ciclo ou da transição física de energia.

O cenário básico de suspensão S3 foi confirmado pelo usuário em 30/10/2026:
ao acordar, a sessão estava pausada e o tempo não avançou. A conferência do perfil
de aceite encontrou `CLOCK_PAUSED reason=suspend`, sessão paused, nenhum intervalo
aberto e `PRAGMA integrity_check=ok`. Os valores numéricos antes/depois de acordar
não foram informados; não se afirma uma comparação temporal independente.

Hibernação física, persistência após reabertura e variações minimizada/Histórico
permanecem **pendentes** até confirmação específica. Siga o
[roteiro manual](manual_power_test.md) para os próximos cenários.

## Incrementos 6 a 8 — relatórios, Histórico e aceite local

Resultados e limites atualizados em [acceptance_report.md](acceptance_report.md).
As consultas usam `tzlocal` e `tzdata` fixados nos locks e o fuso é injetável nos
testes. `test_reports.py` inclui UTC, fusos históricos, dias de 23/25/23,5 horas,
fold, data local suprimida, 35+35 s, snapshots e 1.000 sessões. `test_history.py`
testa callbacks, calendário independente, sessões ao vivo e paginação.

O aceite com Tk real é opt-in e deve ser executado em Windows com Tcl/Tk:

```powershell
$env:STUDYTIMER_NATIVE_UI = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_native_ui.py -s
Remove-Item Env:STUDYTIMER_NATIVE_UI
```

`tests/native_ui_scenarios.py` executa cada cenário em processo próprio, com
uma raiz Tk e banco temporário. Cobre ciclo, mínimo 900×600, navegação, falha de
fechamento, recuperação, rede indisponível na API socket, restauração e primeira
página de 1.000 sessões. A navegação verifica a ordem real dos contêineres das
telas; inspecionar somente os valores dos widgets não detectava o Histórico
encoberto pelo Cronômetro. A correção usa o `lift()` público do contêiner rolável.
O bloqueio de socket não certifica firewall do EXE nem
substitui a execução em Windows sem Python, que foi adiada pelo usuário.

Build oficial validado com Python 3.12.10 x64 e Tcl/Tk 8.6: pip check, Ruff,
formatação e mypy aprovados; 235 testes sem marca build e 1 smoke test aprovados,
incluindo os quatro cenários Tk opt-in. O smoke exige banco inicializado,
recursos empacotados, processo vivo e `APPLICATION_READY`, sem STARTUP_FAILED.
Não basta manter um processo vivo com uma caixa de erro de inicialização aberta.

A janela do EXE foi exercitada localmente em AppContainer sem capabilities de
rede: ciclo completo, navegação durante contagem, detalhes, troca de mês,
fechamento e dados preservados na reabertura e substituição da pasta do programa.
Esse teste não usou o banco pessoal e não alterou configurações de segurança.
O [roteiro da VM](distribution_acceptance.md) registra o aceite que falta.
