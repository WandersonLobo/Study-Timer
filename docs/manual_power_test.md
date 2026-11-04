# Aceite manual de suspensão e hibernação

Use somente nomes e dados de teste. A execução abaixo mantém banco, backups e
logs em `%LOCALAPPDATA%\StudyTimer-Acceptance\StudyTimer\`, separados do perfil
normal `%LOCALAPPDATA%\StudyTimer\`. Não é necessário alterar o aplicativo.

## Evidência histórica do ambiente físico

- Python 3.12.10 x64, instalador completo oficial com assinatura válida da PSF.
- Tcl/Tk 8.6 e pip na instalação; dependências na `.venv` do projeto.
- Instalação das dependências com `--require-hashes --only-binary=:all:`.
- Na validação histórica abaixo, `pip check`, Ruff, formatação e mypy passaram; suíte com 189 aprovados e um
  smoke test de build pulado. A janela Tk real foi conferida no estado Pronto.
- Consulte os estados disponíveis no ambiente de teste com `powercfg /a`.
- Suspensão S3: usuário confirmou pausa e ausência de avanço ao acordar;
  log e banco conferidos. Hibernação e variações ainda pendentes.

Para abrir novamente o mesmo perfil de teste, execute na raiz em PowerShell:

```powershell
$previousLocalAppData = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = Join-Path $previousLocalAppData 'StudyTimer-Acceptance'
    .\.venv\Scripts\python.exe main.py
}
finally {
    $env:LOCALAPPDATA = $previousLocalAppData
}
```

O redirecionamento vale somente durante esse comando. Abra uma instância por vez.
Para desenvolvimento normal, use `.\.venv\Scripts\python.exe main.py` sem
redirecionamento. Não use dados pessoais no perfil de aceite.

## 1. Suspensão

1. Salve seu trabalho em outros programas. No StudyTimer, inicie uma sessão
   chamada **Teste de suspensão**.
2. Deixe contar pelo menos 10 segundos. Anote o tempo e selecione manualmente
   **Iniciar → Energia → Suspender** no Windows, sem pausar o aplicativo antes.
3. Aguarde aproximadamente 30 segundos com o computador suspenso e acorde-o.
4. Desbloqueie o Windows e observe o StudyTimer por 10 segundos. Deve estar
   **Pausado**, com o nome bloqueado e o botão **Retomar** disponível. O total
   deve ficar parado. Pode haver avanço entre sua anotação e o instante em que
   o computador efetivamente entrou em suspensão; o período dormindo deve ser excluído.
5. Clique em **Retomar**, conte mais alguns segundos e confirme que o total
   aumenta a partir do valor preservado. Clique em **Pausar**.
6. Feche e reabra pelo comando acima. No diálogo, escolha **Cancelar** para
   manter pausado e conferir o total persistido. Finalize essa sessão.

Se houver erro, contagem automática após acordar ou salto próximo do tempo
dormindo, anote o ocorrido e não considere o cenário aprovado.

## 2. Hibernação

1. Inicie outra sessão chamada **Teste de hibernação**, deixe contar 10 segundos
   e anote o total. Não pause manualmente o aplicativo.
2. Se disponível no menu de energia, selecione **Hibernar**. Outra opção é fechar
   as janelas de menu, focar a Área de Trabalho e usar **Alt+F4**, escolhendo
   **Hibernar** na lista de ações do Windows.
3. Se a opção não aparecer, registre isso e peça orientação antes de mudar a
   configuração. Não use desligamento/reinicialização como substituto.
4. Aguarde a hibernação concluir, ligue o computador e desbloqueie o Windows.
5. Repita a conferência de estado pausado, total parado por 10 segundos,
   retomada explícita e persistência após fechar/reabrir.

## Variações e evidência

Depois do cenário básico, repita com a janela minimizada e na tela Histórico.
O cronômetro e o monitor de energia devem continuar compartilhados pela janela.
Os logs de teste ficam em `StudyTimer-Acceptance\StudyTimer\logs\studytimer.log`.
`CLOCK_PAUSED reason=suspend` comprova que a pausa foi provocada pelo evento;
`tick_gap` ou `clock_change` indica a proteção complementar e exige investigar
por que o evento nativo não foi observado naquele teste.

Informe os resultados neste formato:

| Cenário | Tempo antes | Tempo ao acordar | Pausado por 10 s? | Retomada explícita e reabertura corretas? |
| --- | --- | --- | --- | --- |
| Suspensão S3 | Não informado | Não informado | Pausa e tempo parado confirmados; duração da observação não informada | Reabertura ainda não confirmada |
| Hibernação | Pendente | Pendente | Pendente | Pendente |

Conferência da suspensão em 30/10/2026: usuário relatou sessão pausada e tempo
sem avanço ao acordar. O log do perfil de aceite contém
`CLOCK_PAUSED reason=suspend`, sem falha registrada nessa transição. A consulta
somente de leitura encontrou a sessão pausada e nenhum intervalo aberto;
`PRAGMA integrity_check` retornou `ok`. Identificadores e durações individuais
não são publicados neste roteiro. A validação básica de suspensão foi confirmada; persistência
após reabertura, variações e hibernação ainda dependem de confirmação específica.

Testes com mensagens Win32 e relógios simulados complementam esse aceite;
não comprovam a transição física do hardware. Nenhum comando deste roteiro
suspende ou hiberna automaticamente o computador.

## Matriz em VM e supervisão externa

O bloco 4 fornece um preparador/validador em
`packaging/windows_acceptance.ps1`, descrito no
[aceite da distribuição](distribution_acceptance.md). Ele **não efetua nem
supervisiona transições**; o operador ou um futuro executor externo deve seguir
este contrato. Nenhuma VM foi iniciada nesta implementação e a matriz real
permanece pendente por falta de um convidado Windows preparado e identificado.

1. Identifique explicitamente o UUID da VM de teste e use somente dados
   sintéticos. Mantenha o host em execução e com trabalho salvo. Não rode um
   comando de energia remotamente sem antes confirmar que o alvo é o Windows
   convidado escolhido. Não suspenda o computador pessoal para validar a VM.
2. Dentro do convidado, consulte `powercfg /a`. Registre separadamente os estados
   de suspensão oferecidos e S4 (hibernação). Se um estado não estiver disponível,
   marque os casos correspondentes como `unsupported`; não habilite hibernação,
   altere firmware ou adapte o host automaticamente. Consulta de disponibilidade
   não comprova que o estado foi atingido.
3. Na conta de teste da VM, abra o pacote com perfil isolado. Para executar o
   binário no mesmo isolamento usado no exemplo Python deste documento, guarde
   o valor de `LOCALAPPDATA`, redirecione-o para `StudyTimer-Acceptance`, execute
   o `.exe` candidato e restaure a variável em `finally`. O programa deve manter
   banco, backups e logs somente nessa árvore de teste; o convidado continua
   sem Python e sem rede.
4. Para cada combinação gerada pelo modo `Plan`, prepare o tema, a tela, o
   estado da sessão e a posição normal/minimizada. A sessão inicialmente
   pausada deve continuar pausada; a sessão contando deve congelar pelo evento
   nativo. Preserve um registro do total congelado no evento antes de dormir.
5. Antes da solicitação, o operador externo inicia um prazo de, por exemplo,
   180 segundos. Solicite **Suspender** ou **Hibernar no Windows convidado**.
   O observador permanece no host, registra a transição e acorda apenas a VM
   escolhida pelos controles do VirtualBox adequados ao estado observado.
   O preparador não implementa esse prazo nem o despertar. Um executor futuro
   precisa implementá-los externamente e limitar suas ações ao UUID explícito.
6. Confirme a transição pelo estado/evento de energia do Windows convidado e
   confira `CLOCK_PAUSED reason=suspend` no perfil sintético. `tick_gap` ou
   `clock_change` isoladamente validam somente a proteção complementar.
   **Pausar a VM ou salvar seu estado no VirtualBox não é suspensão/hibernação
   do Windows.** `controlvm resume` desfaz uma pausa do hipervisor; não comprova
   despertar de S4. Reiniciar ou restaurar snapshot também não substitui S4.
   Consulte os comandos do hipervisor em sua
   [documentação oficial](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/vboxmanage.html).
7. Depois do despertar, observe por ao menos 10 segundos: estado pausado,
   total sem avanço e nenhum intervalo aberto. Retome explicitamente, pause,
   feche e reabra para conferir persistência. Verifique o total congelado
   contra o total ao acordar e após a observação; o tempo dormindo não entra
   na duração. Uma anotação humana anterior ao clique em Suspender pode ser
   menor que o congelamento efetivo e não serve como igualdade exata.
8. Se o prazo vencer, registre falha/pendência e investigue manualmente a VM.
   Não desligue, reinicie, restaure snapshots nem envie comandos de energia ao
   host automaticamente. Não preencha um resultado aprovado para contornar um
   estado indisponível. Não registre credenciais em comandos ou evidências.

Para um caso de energia aprovado, acrescente ao registro de resultado os
booleanos verdadeiros `guest_transition_confirmed`, `power_event_received`,
`sleep_excluded`, `paused_after_resume`, `explicit_resume_only` e
`reopen_preserved`. `transition` deve ser `guest_sleep` em suspensão e
`guest_s4` em hibernação; use o ID exato do caso preparado. São obrigatórios
os inteiros não negativos `open_intervals_after`, `frozen_total_s`,
`total_after_resume_s` e `total_after_observation_s`: não use texto, decimais
ou valores booleanos. O número de intervalos abertos precisa ser zero e os
três totais precisam ser iguais. Exemplo de **estrutura**, sem evidência real:

```json
{
  "id": "power-hibernate-running-history-minimized-dark",
  "status": "pending"
}
```

O validador rejeita uma declaração `passed` sem esses campos consistentes,
mas depende da honestidade e rastreabilidade da medição do operador. Não é um
driver de automação nem comprovação de energia física. Execute a matriz
separadamente em cada Windows alvo. Os resultados de VM e os resultados
físicos históricos desta página devem permanecer separados.
