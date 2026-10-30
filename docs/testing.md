# Plano de validação

Os arquivos de teste seguem a estrutura da seção 10 do PDF. Arquivos reservados
apenas com docstring não representam testes executados nem requisitos aprovados.

| Arquivo | Cobertura prevista | Situação inicial |
| --- | --- | --- |
| `test_bootstrap.py` | Caminhos, logs e inicialização (parte CT-11/27) | Base e recuperação antes de criar a janela |
| `test_repository.py` | PRAGMAs, índices, checks, transações (parte CT-09/15) | Testes da base |
| `test_database_safety.py` | Corrupção, WAL, backups e restauração | Testes de segurança |
| `test_security.py` | Nome, SQL, privacidade, pacote, lock e infraestrutura offline | Testes de segurança |
| `test_clock.py` | Parte de CT-03/12/13/16: monotônico, lacunas, correção civil e snapshots | Relógio confiável com fonte simulada |
| `test_ui_states.py` | CT-01/03/16/17/26 | Reservado |
| `test_timer.py` | CT-02/03, parte de CT-04/09/12/13/15/18 | Ciclo de sessão sem interface e rollback real |
| `test_reports.py` | CT-05/06/07/14/25 | Reservado |
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

O ambiente disponível inicialmente contém Python 3.14 sem Tkinter e um registro
do launcher apontando para uma instalação ausente. Isso não valida a linha-alvo
3.12 nem a interface. Para verificar esta entrega, foi preparado um runtime
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
A suspensão simulada valida o detector conservador; CT-13 ainda exige integração
e teste de suspend/hibernate real no Windows. O incremento 2 cobre a mudança de
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
esses cenários são cobertos pelo incremento 3. Fechamento de janela, modais e
eventos reais de energia do Windows continuam pendentes.

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
Agendamento dos callbacks, diálogos de erro e eventos Windows ainda precisam de
integração e validação na UI. O build continua condicionado à geração do pacote.

Validação do incremento em 30/10/2026, no runtime temporário Python 3.12.10 x64:
`python -m pytest --basetemp .pytest_cache/persistence-final` aprovou 153 testes,
com um smoke test pulado por ausência de build. `python -m ruff check .`,
`python -m ruff format --check .`, `python -m mypy` e `git diff --check` passaram.
`python -m pip check` não pôde executar: esse runtime não contém o módulo pip.
Dependências e locks não foram alterados nesta etapa.
