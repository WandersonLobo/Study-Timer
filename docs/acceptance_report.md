# Aceite do MVP e da distribuição

Registro de 30/10/2026. Dados sintéticos e bancos temporários, sem dados pessoais.
Ambiente de desenvolvimento: Windows x64, Python 3.12.10, Tcl/Tk 8.6,
dependências fixadas com hashes. Nenhum commit é produzido por esta validação.

## Relatórios e Histórico

| Critério | Resultado | Evidência |
| --- | --- | --- |
| Hoje, semana de segunda a domingo, mês atual e mês selecionado | Aprovado | `test_reports.py`, `test_history.py` |
| Viradas de dia, semana, ano, mês e fevereiro bissexto | Aprovado | Fronteiras meio abertas, sem perda/dupla soma |
| Fusos e DST | Aprovado | Nova York: 23/25 h e fold; São Paulo: meia-noite inexistente; Havana: meia-noite ambígua; Lord Howe: 23,5 h; Apia: dia suprimido |
| 35 s + 35 s = 1 minuto após agregação | Aprovado | 70 segundos no serviço e 1 min nos cartões reais do modelo de UI |
| Snapshot antes do heartbeat, sem dupla soma | Aprovado | Snapshot substitui checkpoint; relatório não escreve no banco |
| Calendário e total selecionados independentes dos cartões | Aprovado | Navegação mensal e seleção de dia em testes integrados |
| Visibilidade ao alternar entre as telas | Aprovado | Teste Tk do empilhamento dos contêineres e navegação visual no executável corrigido |
| Intensidade, dias vazios e sessões zeradas | Aprovado | Faixas absolutas e zero atribuído ao dia de criação |
| 1.000 sessões: consultas em até 2 s | Aprovado | 0,021 s na medição inicial dos três relatórios |
| 1.000 sessões: primeira página com Tk real em até 2 s | Aprovado | 0,205 s; detalhes limitados inicialmente a 50 sessões |

Os tempos são medições locais, não garantias para outro equipamento.

## Fluxos e persistência

| Critério | Resultado | Evidência/limite |
| --- | --- | --- |
| Iniciar, pausar, retomar e finalizar, com nome bloqueado | Aprovado | Callbacks dos botões com Tk real e fonte temporal simulada |
| Janela 900×600 e navegação durante contagem | Aprovado local | Tk real; células sem transbordamento horizontal; Histórico rolável |
| Falha de COMMIT ao fechar e repetição segura | Aprovado | Janela permanece aberta e snapshot não contabiliza espera |
| Falhas de leitura, disco cheio, banco bloqueado/somente leitura | Aprovado automatizado | SQLite real e testes de recuperação/serviço |
| Recuperação após saída abrupta e novo processo | Aprovado | WAL e checkpoints, sem tempo do processo fechado |
| Backup/restauração e retenção | Aprovado | API SQLite, validação e preservação pré-restauração; cenário com Tk real |
| UI com sockets indisponíveis | Aprovado automatizado | Bloqueio por exceção no acesso à API socket; não equivale a firewall do executável |
| Suspensão S3 física | Confirmado pelo usuário | Estado pausado e tempo estável; log `reason=suspend`, banco íntegro |
| Hibernação física | Pendente | Usuário optou por testar ao final; seguir `manual_power_test.md` |
| Todas as escalas DPI e variações de hardware | Pendente | Uma janela mínima local não comprova toda a matriz de equipamentos |

Cada cenário nativo roda em processo próprio, mantendo uma única raiz Tk como
na aplicação. Diálogos são substituídos nos testes automatizados para evitar
modais bloqueantes; a lógica das três escolhas é coberta por `test_ui_states.py`.

## Distribuição

| Critério | Estado |
| --- | --- |
| Build pelo script oficial, smoke, ZIP e SHA-256 | Aprovado local: Python 3.12.10 x64; pip check, Ruff, formatação e mypy; 235 testes e 1 smoke test aprovados |
| Pacote sem dados pessoais ou caminhos privados detectáveis | Aprovado no escopo inspecionado: scanner no onedir e ZIP extraído; inspeção adicional de 420 payloads descomprimidos e 10.758 objetos de código |
| Execução no host de desenvolvimento | Aprovado local: ciclo completo, pausa estável, Histórico rolável, cartões e navegação mensal pela janela real do EXE |
| Substituição da pasta do programa preserva os dados | Aprovado local: SHA-256 dos registros sintéticos de sessões/intervalos inalterado antes de novas ações; mesmo esquema/versão |
| Fechamento e reabertura do executável | Aprovado local: saída normal com paused, sem intervalo aberto; novo processo inicializou com os mesmos 6 segundos confirmados |
| Executável em ambiente local sem permissões de rede | Aprovado local: AppContainer=1, sem capabilities de rede; sondagem de conectividade bloqueada; ciclo e Histórico funcionaram |
| Windows limpo sem Python | Pendente por decisão do usuário: VM ainda sem Windows/ISO |
| Windows limpo sem Python e com rede da VM desconectada | Pendente junto ao aceite da VM; seguir o roteiro preparado |

Pacote local: `StudyTimer-Windows-v0.1.0.zip`, 14.397.682 bytes.
SHA-256:

```text
56ecefdf206d02075cde68ab5fb044604606abcf2b2fdd4868b074ba9169a455
```

O build revelou incompatibilidade do altgraph antigo com setuptools sem
pkg_resources; os pins de PyInstaller, hooks e altgraph foram atualizados.
A execução restrita revelou também uma falha de bibliotecas ao escrever em
stderr ausente no EXE sem console. A entrada agora prepara streams ausentes,
e o smoke exige `APPLICATION_READY` após construir a interface. A inspeção
visual encontrou o Histórico encoberto pelo Cronômetro; a navegação foi corrigida
para elevar o contêiner rolável externo. Os candidatos anteriores foram retirados
de `dist`; somente o ZIP corrigido e seu SHA-256 permanecem na saída final.

O teste de rede usou a restrição do sistema operacional no AppContainer, sem
alterar firewall, antivírus ou configurações de privacidade. Ele é distinto do
teste automatizado de sockets e não comprova o cenário da VM sem Python.
Tcl/Tk e Python estão presentes no host; variáveis e PATH de Python foram
retirados do ambiente do executável durante o teste. A comparação de dados
não exercita uma migração de esquema, pois a versão do esquema continua 1.

O pacote só poderá ser declarado aprovado para distribuição após os aceites
pendentes relevantes. Não se considera um host com Python instalado equivalente
a uma VM limpa. Nenhum teste suspende/hiberna o computador automaticamente ou
desativa proteções de segurança do Windows.
O passo a passo do aceite adiado está em
[distribution_acceptance.md](distribution_acceptance.md).

## Privacidade

Os relatórios públicos usam referências genéricas, sem nome de conta, caminho
de perfil, IDs de sessão, inventário do equipamento ou conteúdo pessoal.
Logs de instalação e caches continuam locais e ignorados pelo Git.
A inspeção complementar descomprimiu os módulos PYZ do executável e os `.pyc`
de `base_library.zip`, sem executar o código extraído. Não encontrou o perfil
privado nos payloads nem caminhos de perfil em `co_filename`. Isso não certifica
todos os formatos possíveis de metadados ou segredos. Os logs do aplicativo
usados no aceite contêm códigos/motivos, sem nomes de sessões ou caminhos privados.
Uma busca por formatos conhecidos de credenciais no histórico local não encontrou
ocorrências; isso não certifica todo tipo de segredo. Foi encontrado endereço de
autoria fora do formato noreply do GitHub nos metadados dos commits. O valor não
é reproduzido aqui, e o histórico não foi alterado. Torná-lo público pode expor
essa autoria. Artefatos remotos do GitHub Actions não foram inspecionados.

## Comandos

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
$env:STUDYTIMER_NATIVE_UI = '1'
.\.venv\Scripts\python.exe -m pytest --basetemp .pytest_cache/mvp-full
.\packaging\build.ps1
Remove-Item Env:STUDYTIMER_NATIVE_UI
```

Na validação final, o script oficial executou as ferramentas de qualidade e
`pytest -m 'not build'` no ambiente novo, seguido de `pytest -m build` após gerar
o onedir. O opt-in nativo estava habilitado também nessa execução do build.

## Bloco 1 — validação posterior do esquema v2 e serviços

Em 04/11/2026, o código-fonte do bloco 1 foi validado em Python 3.12.10 x64 no
Windows, usando apenas bancos temporários e relógios simulados. A migração
preserva os registros anteriores e tem testes de rollback de DDL/COMMIT e
encerramento abrupto antes da confirmação. A restauração de backups v1/v2 e a
proteção da origem durante a retenção também foram verificadas.

Pip check, Ruff, formatação e mypy passaram. A suíte completa aprovou 286 testes,
com cinco pulados: quatro cenários Tk opt-in e um smoke sem pacote gerado.
Executados separadamente com opt-in ativo, os quatro cenários Tk passaram,
confirmando o ciclo e a compatibilidade da interface atual com o esquema v2.
Comandos e cobertura estão em [testes](testing.md#bloco-1--tipos-preferências-e-migração-v1-para-v2).

O executável e o SHA-256 registrados anteriormente pertencem à entrega com
esquema v1. Não houve novo build neste bloco; aqueles aceites não certificam
um pacote contendo v2. Não foram realizados novos testes de energia física ou
Windows limpo. Os controles de tipos, temas e novos gráficos continuam para
os blocos seguintes, que aguardam o commit do usuário.
