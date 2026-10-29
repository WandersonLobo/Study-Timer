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
consulta da sessão pendente. As ações da interface estão desabilitadas.

Os demais métodos dos serviços levantam `NotImplementedError` explicitamente.
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
2. Implementar relógio, sessões e heartbeat com testes controlados.
3. Implementar recuperação, tratamento de falhas de escrita e eventos Windows.
4. Implementar relatórios e fronteiras locais, incluindo DST e mudança de fuso.
5. Conectar as duas telas, estados visuais, modais e calendário mensal.
6. Incorporar SVGs aprovados e substituir o ícone provisório.
7. Executar a matriz de aceite, build e teste em Windows sem Python instalado.
