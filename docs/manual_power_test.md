# Aceite manual de suspensão e hibernação

Use somente nomes e dados de teste. A execução abaixo mantém banco, backups e
logs em `%LOCALAPPDATA%\StudyTimer-Acceptance\StudyTimer\`, separados do perfil
normal `%LOCALAPPDATA%\StudyTimer\`. Não é necessário alterar o aplicativo.

## Ambiente

- Python 3.12.10 x64, instalador completo oficial com assinatura válida da PSF.
- Tcl/Tk 8.6 e pip na instalação; dependências na `.venv` do projeto.
- Instalação das dependências com `--require-hashes --only-binary=:all:`.
- `pip check`, Ruff, formatação e mypy passaram; suíte com 189 aprovados e um
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
