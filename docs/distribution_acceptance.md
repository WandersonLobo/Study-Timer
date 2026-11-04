# Roteiro de aceite da distribuição

O aceite em Windows limpo foi adiado pelo usuário: a VM ainda não tem Windows
nem ISO. Este roteiro fica preparado para quando houver Windows 10/11 x64 sem
Python instalado. Os resultados locais estão em [acceptance_report.md](acceptance_report.md).

## Preparação na VM

1. Use somente dados sintéticos. Não copie o banco pessoal para a VM.
2. Copie o ZIP completo e seu arquivo `.sha256` para uma pasta de teste.
3. No PowerShell da VM, compare o SHA-256 do ZIP com o hash obtido de uma fonte
   confiável. O arquivo `.sha256` que acompanha o ZIP também deve corresponder:

   ```powershell
   $archive = '.\StudyTimer-Windows-v0.1.0.zip'
   $expected = ((Get-Content -LiteralPath "$archive.sha256").Trim() -split '\s+')[0]
   $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
   if ($actual -ne $expected) { throw 'SHA-256 divergente' }
   ```

4. Confirme que nenhum Python foi instalado no Windows da VM. Um alias da
   Microsoft Store chamado `python.exe` não comprova a presença do runtime.
5. Desconecte o adaptador de rede **da VM** no VirtualBox e confirme que o Windows
   convidado está sem conectividade. Preserve as proteções de segurança do host
   e do convidado. Não desative antivírus para executar o teste.
6. Extraia a pasta completa para `release-a`. Não execute apenas o `.exe`
   separado de `_internal` e dos demais recursos.

## Ciclo e recuperação

1. Abra `release-a\StudyTimer\StudyTimer.exe`. Não deve ser necessário instalar
   Python, baixar dependências ou conectar-se à rede.
2. Crie um tipo sintético, selecione-o e inicie uma sessão com descrição sintética.
   Confirme tipo/descrição bloqueados e botões coerentes. Pause, aguarde e retome:
   o intervalo pausado não deve entrar no total. Teste também uma sessão Sem tipo.
3. Finalize duas sessões de aproximadamente 35 segundos do mesmo tipo. No modo
   Dia do Histórico, o total deve mostrar 1min depois da soma. Os detalhes mantêm
   os segundos de cada sessão e o ranking atribui os 70 segundos ao mesmo tipo.
4. Inicie outra sessão e abra Histórico antes do primeiro heartbeat de 5 s.
   Os detalhes devem mostrar tempo em andamento. Alterne Dia/Semana/Mês e navegue
   para um período anterior: métrica, gráfico, ranking e sessões devem se referir
   ao período selecionado. Selecione uma barra diária, confira seu Dia e volte
   ao período de origem. Use o calendário compacto para escolher uma data.
   Filtre um tipo e Sem tipo, remova o filtro com Todos os tipos e confirme
   que Hoje mantém o modo e retorna ao período atual. Volte ao Cronômetro sem
   perder ou interromper a sessão.
5. Feche durante a contagem e reabra. A sessão deve reaparecer pausada, sem
   contabilizar o tempo com o programa fechado. Teste as três escolhas do diálogo
   de recuperação em execuções separadas.
6. Para a saída abrupta, use uma sessão sintética: deixe passar um heartbeat,
   encerre seu processo pelo Gerenciador de Tarefas e reabra. A recuperação deve
   usar o último checkpoint confirmado e continuar pausada. Pode perder o trecho
   posterior ao checkpoint; não pode contar o intervalo em que o app esteve fechado.
7. Confira legibilidade e navegação em 900×600 e na escala DPI usada na VM.
   Verifique Claro/Escuro, foco, seleção por teclado, descrições longas,
   lista com Mostrar mais, gráfico vazio e manutenção da rolagem durante ticks.
8. Na Semana/Mês, confira a média com os dias transcorridos até hoje no período
   atual e todos os dias, inclusive sem estudo, no período passado completo.
   Uma sessão atravessando meia-noite deve contribuir em cada dia apenas com
   sua parcela, sem duplicar o total. Um tipo arquivado continua no histórico.
   Troque o tema e reabra a aplicação: a aparência deve persistir.

## Substituição da pasta do programa

1. Finalize ou pause a sessão e feche o aplicativo normalmente.
2. Extraia novamente o pacote completo em `release-b`, sem copiar ou modificar
   `%LOCALAPPDATA%\StudyTimer\`.
3. Abra `release-b\StudyTimer\StudyTimer.exe` na mesma conta Windows. Os totais,
   nomes sintéticos e a sessão pausada devem permanecer disponíveis.
4. Registre o resultado como substituição de pasta no mesmo esquema/versão.
   Para a atualização de origem v1, use somente banco legado sintético: confirme
   o backup em before-migration, migração v2 e preservação dos registros antes
   de validar o Histórico. As mudanças do bloco 3 não criam outra versão do
   esquema. O teste com fonte não substitui a verificação do pacote candidato.

O pacote aceito em uma entrega anterior ao bloco 3 não certifica estes novos
fluxos. Gerar o candidato pelo script oficial e registrar a versão e SHA-256
efetivamente usados. A execução automática completa pertence ao bloco 4; este
documento é um roteiro de aceite, não evidência de execução nem ativação de CI.

O primeiro teste sem rede não exige alterar o firewall. Um teste adicional com
regra de firewall específica para o executável pode ser registrado separadamente,
sem desativar o antivírus nem outras proteções.

## Registro do resultado

Atualize [acceptance_report.md](acceptance_report.md) com data, versão do Windows,
versão do pacote, SHA-256, resultado de cada fluxo e limitações. Não inclua nome
da conta, caminho privado, inventário da máquina ou dados pessoais em prints/logs.

O teste físico de hibernação no computador segue o
[roteiro de energia](manual_power_test.md). Hibernar uma VM não comprova a entrega
de eventos de energia pelo hardware do computador de destino.
