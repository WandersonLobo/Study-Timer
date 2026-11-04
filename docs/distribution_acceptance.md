# Roteiro de aceite da distribuição

O aceite em Windows limpo permanece pendente: não foi disponibilizada uma VM
Windows preparada. O VirtualBox 7.2.16 foi encontrado fora do PATH, mas sua
consulta de inventário retornou `E_ACCESSDENIED`; nenhuma VM foi iniciada ou
alterada nesta validação. Este roteiro fica preparado para Windows 10/11 x64 sem
Python instalado. Os resultados locais estão em [acceptance_report.md](acceptance_report.md).

## Preparação e validação das evidências

`packaging/windows_acceptance.ps1` prepara a matriz e valida **registros do
operador**. Ele não controla o VirtualBox, não transfere arquivos, não executa
ações na interface e não inicia, suspende, acorda ou supervisiona máquinas.
Também não transforma resultados simulados em comprovação de energia real.
Sua execução depende de um ZIP candidato produzido por `packaging/build.ps1`,
um SHA-256 confiável e do UUID conhecido da VM de teste. Não use o UUID de uma
máquina pessoal ou qualquer alvo inferido automaticamente.

Na raiz do projeto, prepare o registro; substitua os valores pelo candidato e
pela VM efetivamente escolhidos:

```powershell
$candidateArchive = '.\dist\StudyTimer-Windows-v0.1.0.zip'
$candidateHash = 'SHA256_DE_64_CARACTERES_OBTIDO_DO_BUILD'
$acceptanceVmId = 'UUID_DA_VM_DE_TESTE'
.\packaging\windows_acceptance.ps1 -Mode Plan -VmId $acceptanceVmId `
    -Archive $candidateArchive -ExpectedSha256 $candidateHash `
    -OutputDirectory '.\.pytest_cache\windows-acceptance-plan'
```

O JSON `windows-acceptance.json` começa com 33 casos pendentes: distribuição e
32 combinações de suspensão/hibernação × sessão contando/pausada ×
Cronômetro/Histórico × janela normal/minimizada × Claro/Escuro. A saída 2 é
intencional: preparar o roteiro não comprova sua execução. Execute uma matriz
separada para cada Windows 10/11 x64 que se pretenda aceitar; um resultado no
Windows 11 não certifica o Windows 10.

Depois de executar os procedimentos abaixo e o [roteiro de energia](manual_power_test.md),
registre a evidência em um JSON separado. Estrutura inicial **incompleta**:

```json
{
  "schema_version": 1,
  "vm_id": "UUID_DA_VM_DE_TESTE",
  "package_sha256": "SHA256_DO_CANDIDATO",
  "environment": {
    "windows": "Windows 11",
    "architecture": "x64",
    "python_absent": true,
    "offline": true,
    "isolated_profile": true,
    "powercfg_checked": true
  },
  "results": [{"id": "distribution", "status": "pending"}]
}
```

Use `true` somente depois de conferir a condição. A ausência de uma condição
verificada impede o aceite, mesmo se os casos forem declarados aprovados.
Cada resultado utiliza um ID gerado pelo modo `Plan` e um estado `passed`,
`failed`, `pending` ou `unsupported`. Não remova casos indisponíveis: a ausência
de resultados também mantém a cobertura pendente. IDs desconhecidos ou
duplicados são rejeitados.

Para declarar `distribution` aprovado, os campos booleanos `hash_verified`,
`types_cycle`, `history_filters`, `theme_persisted`, `reopen_preserved`,
`migration_preserved` e `directory_replacement` precisam ser verdadeiros,
correspondendo aos procedimentos deste documento. Os campos de energia estão
descritos no roteiro específico. Valide o registro:

```powershell
.\packaging\windows_acceptance.ps1 -Mode ValidateEvidence -VmId $acceptanceVmId `
    -Archive $candidateArchive -ExpectedSha256 $candidateHash `
    -EvidenceFile '.\.pytest_cache\evidence-windows11.json' `
    -OutputDirectory '.\.pytest_cache\windows-acceptance-result'
```

| Código | Significado |
| --- | --- |
| 0 | Todos os registros obrigatórios foram fornecidos e são consistentes (`evidence-complete`). |
| 1 | Hash, identidade, formato ou invariantes inválidos; ou um caso falhou (`failed`). |
| 2 | Preparação ou cobertura incompleta, incluindo estado não suportado (`pending`). |

O resumo descarta textos livres, caminhos e detalhes arbitrários do registro.
Ele mantém `hardware_certified: false`: o validador verifica o contrato dos
dados declarados, não autentica observações, screenshots ou eventos do Windows.
Os testes automatizados desse contrato usam evidências sintéticas, sem acessar
VirtualBox, banco pessoal ou estados de energia. Não publique registros brutos
que contenham informações privadas. Falta de VM, Windows, estado de energia ou
executor externo deve constar como pendência no relatório, sem aprovação da CI.

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
fluxos. Gere o candidato pelo script oficial e registre a versão e SHA-256
efetivamente usados. Os testes externos de desktop do bloco 4 complementam este
roteiro. O preparador de evidências não executa a matriz na VM; esse aceite
continua dependendo do ambiente e da execução registrados.

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
