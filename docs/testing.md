# Plano de validação

Os arquivos de teste seguem a estrutura da seção 10 do PDF. Arquivos reservados
apenas com docstring não representam testes executados nem requisitos aprovados.

| Arquivo | Cobertura prevista | Situação inicial |
| --- | --- | --- |
| `test_bootstrap.py` | Caminhos, logs e inicialização (parte CT-11/27) | Testes da base |
| `test_repository.py` | PRAGMAs, índices, checks, transações (parte CT-09/15) | Testes da base |
| `test_database_safety.py` | Corrupção, WAL, backups e restauração | Testes de segurança |
| `test_security.py` | Nome, SQL, privacidade, pacote, lock e infraestrutura offline | Testes de segurança |
| `test_ui_states.py` | CT-01/03/16/17/26 | Reservado |
| `test_timer.py` | CT-02/03/10/12/13 | Reservado |
| `test_reports.py` | CT-05/06/07/14/25 | Reservado |
| `test_recovery.py` | CT-04/08/18/19 | Reservado |
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
