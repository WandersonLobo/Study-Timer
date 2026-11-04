# StudyTimer

Aplicativo desktop de estudos para Windows 10/11 x64, feito com Python 3.12,
CustomTkinter e SQLite. Dados locais, uso offline e somente duas telas:
Cronômetro e Histórico. Baseado na especificação técnica v1.1 revisada.

**Estado atual: cronômetro, recuperação, relatórios e Histórico.** Iniciar,
pausar, retomar, finalizar e salvar checkpoints funcionam pelos serviços e testes
com SQLite. Ao abrir, uma sessão interrompida é recuperada como pausada até o
último checkpoint confirmado, excluindo o tempo com o programa fechado. Falhas
de persistência interrompem a contagem e são sinalizadas sem confirmar dados.
A tela Cronômetro permite iniciar, pausar, retomar e finalizar, com atualização
de 250 ms e heartbeat de 5 s. O nome fica bloqueado até finalizar a sessão.
Ao reabrir, um diálogo permite retomar, finalizar ou manter a sessão pausada.
Fechar a janela salva uma pausa; falhas mantêm a janela aberta para nova tentativa.
Suspensão/hibernação e retomada do Windows congelam a contagem e mantêm a sessão
pausada até uma retomada explícita. O detector de lacunas continua complementar.
O Histórico inclui cartões atuais, calendário mensal navegável, intensidade e
sessões por dia, com atualização antes do heartbeat. Relatórios usam fusos
históricos e somam segundos antes de truncar minutos.
O aceite local está registrado em [resultados](docs/acceptance_report.md).
Hibernação física e Windows limpo na VM permanecem pendentes.

**Bloco 1 — dados e serviços:** o esquema v2 acrescenta tipos de estudo e uma
preferência de aparência, com migração explícita do banco v1. Os serviços permitem
criar, renomear, recolorir, arquivar e reativar tipos, iniciar uma sessão com tipo
opcional e persistir Claro/Escuro. Estudos anteriores permanecem sem tipo, com
seus nomes, estados e segundos preservados. A preferência inicial é Escuro.
**Bloco 2 — Cronômetro e temas:** o Cronômetro permite selecionar Sem tipo ou
um tipo cadastrado, criar tipos e gerenciar nome, cor, arquivamento e reativação.
Tipo e descrição ficam bloqueados até finalizar a sessão. Uma finalização salva
limpa a descrição e mantém a seleção de tipo para o próximo estudo nesta abertura.
O seletor Claro/Escuro na base da barra lateral salva e reaplica a aparência,
inclusive após reabrir. As telas não exibem instruções permanentes; estados e
avisos necessários permanecem. O Histórico mantém seu calendário e relatórios
atuais, com contraste nos dois temas. Novos gráficos e ampliação da CI pertencem
aos blocos 3 e 4, aguardando o commit desta etapa. Veja [arquitetura](docs/architecture.md).

## Estrutura

```text
Study-Timer/
├── main.py                       # Composição e entrada do aplicativo
├── pyproject.toml                # Python alvo, pytest, Ruff e mypy
├── requirements.txt              # Baseline fixada de execução
├── requirements-dev.txt          # Baseline fixada de desenvolvimento/build
├── requirements*.in              # Pins usados para gerar os locks com hashes
├── assets/                       # Ícone provisório do aplicativo
├── app/
│   ├── application.py            # Janela e navegação
│   ├── config.py                 # Constantes e LOCALAPPDATA
│   ├── logging_config.py         # Logs rotativos
│   ├── single_instance.py        # Lock por perfil Windows
│   ├── windows_power.py          # Suspensão e retomada sem contagem automática
│   ├── validation.py             # Normalização do nome de sessão
│   ├── models/                   # Um arquivo por dataclass ou enumeração
│   │   ├── __init__.py           # Exportações públicas dos modelos
│   │   ├── appearance_mode.py
│   │   ├── clock_reading.py
│   │   ├── clock_snapshot.py
│   │   ├── pause_reason.py
│   │   ├── period_totals.py
│   │   ├── session.py
│   │   ├── session_status.py
│   │   ├── session_summary.py
│   │   ├── study_interval.py
│   │   ├── study_color.py
│   │   ├── study_type.py
│   │   └── ui_state.py
│   ├── ui/
│   │   ├── timer_view.py
│   │   ├── history_view.py
│   │   ├── theme.py               # Paleta e adaptação de teclado Claro/Escuro
│   │   ├── study_type_dialog.py   # Cadastro e gerenciamento de tipos
│   │   ├── formatting.py          # Formatação após agregação
│   │   └── startup_dialog.py      # Erros sem caminhos privados
│   ├── services/
│   │   ├── clock_service.py       # Fonte de relógio injetável
│   │   ├── timer_service.py       # Sessões, checkpoints e recuperação
│   │   ├── study_type_service.py  # Validação e operações de tipos
│   │   ├── preferences_service.py # Preferência local de aparência, sem widgets
│   │   └── report_service.py      # Fronteiras locais, DST e snapshots
│   └── database/
│       ├── connection.py          # Conexão e PRAGMAs
│       ├── backup.py              # API SQLite, retenção e restauração validada
│       ├── health.py              # Integridade, versão e preservação de corrupção
│       ├── schema_version.py      # Versão atual e versões de origem suportadas
│       ├── migrations.py          # Migração explícita v1 para v2
│       ├── repository.py          # Transações e invariantes
│       └── schema.sql            # Tabelas, checks, índices e trigger
├── docs/
│   ├── architecture.md
│   ├── testing.md
│   ├── security.md
│   ├── acceptance_report.md       # Resultados e limites do aceite local
│   ├── distribution_acceptance.md # Roteiro do aceite adiado na VM
│   └── mockups/                  # Aguardando SVGs aprovados
├── packaging/
│   ├── StudyTimer.spec           # Fonte única do build onedir
│   ├── check_bundle.py           # Bloqueio de dados privados no pacote
│   ├── lock_dependencies.py      # Geração dos hashes das wheels
│   └── build.ps1                 # Qualidade, build, smoke, ZIP e SHA-256
├── tests/                        # Testes de serviços, persistência, UI e build
└── .github/workflows/ci.yml       # Qualidade em Windows/Python 3.12
```

## Desenvolvimento

Instale Python **3.12 x64 com Tcl/Tk** no Windows. Na raiz do repositório:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip --isolated install --index-url https://pypi.org/simple --require-hashes --only-binary=:all: -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py
```

Não é necessário ativar a venv. O build local foi validado com Python 3.12.10
x64 e as dependências fixadas nos locks; consulte os resultados de aceite.
Não há suporte declarado a Python 3.13+.

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
```

Consulte [arquitetura](docs/architecture.md), [diagrama de classes UML](docs/uml_diagram.md)
e [plano de testes](docs/testing.md)
para os contratos, limites desta etapa e próximos passos.

## Dados e logs

- Banco: `%LOCALAPPDATA%\StudyTimer\estudos.db`.
- Log rotativo: `%LOCALAPPDATA%\StudyTimer\logs\studytimer.log`.
- Backups automáticos: `%LOCALAPPDATA%\StudyTimer\backups\` (últimos cinco).
- Antes da migração: `backups\before-migration\`, com retenção própria de cinco.
- Antes da restauração: `backups\before-restore\`, com retenção própria de cinco.
- Recursos do programa ficam separados dos registros do usuário.
- O anexo SQL original e os SVGs citados no PDF não foram fornecidos. O esquema
  inicial foi reconstruído do texto; referências aguardadas em `docs/mockups/`.

## Build Windows

Com a venv Python 3.12 x64 criada, execute no Windows:

```powershell
.\packaging\build.ps1
```

O script usa exclusivamente [StudyTimer.spec](packaging/StudyTimer.spec), inclui
os recursos do CustomTkinter, roda o teste de abertura e compacta a pasta inteira
`dist/StudyTimer/`. Gera `StudyTimer-Windows-v0.1.0.zip` e o arquivo `.sha256`.
O ícone atual é provisório. O build e o smoke locais foram aprovados; o aceite
em Windows limpo continua pendente.
O build cria um ambiente novo em `C:\StudyTimerBuild\<id>`, copia apenas fontes e
recursos e bloqueia arquivos pessoais antes de gerar a saída final. A pasta deve
ser gravável; `-BuildRoot` permite informar outro diretório neutro fora do perfil.
O executável intermediário fica nessa pasta; a saída final contém ZIP e SHA-256.

## Instalação e suporte da futura distribuição

Extraia o ZIP completo e abra `StudyTimer.exe` dentro da pasta extraída.
O computador de destino não precisará de Python. Essa entrega ainda deve ser
testada em Windows limpo antes de ser anunciada como pronta.

Confira a procedência do pacote e compare o SHA-256 com o publicado pelo projeto:

```powershell
Get-FileHash .\StudyTimer-Windows-v0.1.0.zip -Algorithm SHA256
```

SHA-256 do pacote local gerado em 30/10/2026 (atualizar a cada novo build):

```text
56ecefdf206d02075cde68ab5fb044604606abcf2b2fdd4868b074ba9169a455
```

O [roteiro da distribuição](docs/distribution_acceptance.md) descreve o aceite
em VM sem Python, com rede desconectada e substituição da pasta do programa.

Executáveis novos sem assinatura podem apresentar aviso do SmartScreen. Verifique
a origem e o hash com o responsável pela distribuição; não desative o antivírus.

Para atualizar, substitua apenas a pasta do programa. Preserve sempre a pasta de
dados em LOCALAPPDATA. Backups automáticos usam a API SQLite e são validados.
A restauração exige aplicativo fechado e valida integridade e versão antes de
alterar o destino; o ponto de integração é `restore_backup()` na camada de banco.
Ainda não existe botão de backup/restauração.

Na primeira abertura de um banco v1, a aplicação valida os dados e cria uma cópia
consistente antes de migrar para v2, sem recriar sessões ou intervalos. Falha no
backup ou na migração impede a abertura normal. Bancos de versões desconhecidas
continuam sendo recusados. O backup v1 pode ser restaurado: sua cópia temporária
é migrada e validada antes de tocar o destino, preservando o arquivo de origem.

Após a migração, executáveis antigos que exigem v1 não abrem o banco v2. Voltar
a pasta do programa não reverte o banco. Não há downgrade automático; uma
reversão exige procedimento explícito, aplicativo fechado e backup compatível,
preservando os dados atuais antes de restaurar. Veja os contratos em
[arquitetura](docs/architecture.md) e [segurança](docs/security.md).

## Segurança e privacidade

Banco, backups e logs são locais; o SQLite não é criptografado. Proteja a conta
com senha e bloqueio do Windows e use BitLocker ou criptografia de dispositivo
quando disponível. Guarde backups em armazenamento protegido, sem compartilhá-los
por mensageiro ou pasta pública. Capturas do histórico também podem revelar nomes.

O banco usa **WAL + synchronous=FULL**, substituindo a decisão anterior de DELETE.
Não copie somente o `.db` enquanto o app estiver aberto; use a API de backup.
Corrupção preserva uma cópia `.corrupt` e interrompe a abertura, sem reparo automático.
Veja [segurança](docs/security.md) para verificações aplicadas, dependências com
hash, instruções de auditoria e limites que ainda exigem teste do executável.
