## Context

O Cetus é um único arquivo Python executável de ~29k linhas. Essa escolha histórica facilita a distribuição (AppImage, .deb, AUR), mas dificulta manutenção, revisão de código e uso de ferramentas de IA, pois qualquer alteração exige carregar o arquivo inteiro. O objetivo é dividir o código em módulos temáticos sem perder a capacidade de gerar o arquivo único.

## Goals / Non-Goals

**Goals:**
- Organizar classes e funções em módulos Python dentro de um pacote `cetuslib/`.
- Preservar a geração do executável monolítico `cetus` para distribuição.
- Manter o aplicativo funcional durante toda a transição.
- Eliminar dependências circulares entre módulos.

**Non-Goals:**
- Reescrever lógica de negócio ou alterar comportamento do usuário.
- Criar testes extensivos agora (serão facilitados, mas não são escopo).
- Remover imediatamente o arquivo `cetus` raiz; ele continuará como entrypoint gerado.
- Modularizar widgets puramente internos (`_CursorOverlay`, `_DisconnectOverlay`) de forma independente se estiverem fortemente acoplados.

## Decisions

1. **Estrutura de módulos por domínio**
   - O pacote foi renomeado para `cetuslib/` para evitar conflito com o executável `cetus` na raiz.
   - `cetuslib/config.py` — `ConfigManager`.
   - `cetuslib/terminal.py` — `TerminalWidget`, `TerminalDialog`, `TerminalTabbedWindow` e widgets auxiliares do terminal.
   - `cetuslib/workers.py` — todos os workers `QThread` (ScanWorker, ConnectionWorker, MtrWorker, etc.).
   - `cetuslib/network.py` — scanners, descoberta, Wi-Fi, traceroute, iperf3 e widgets de rede.
   - `cetuslib/transfer.py` — SFTP, FTP, SMB e widgets de transferência.
   - `cetuslib/ui/` — widgets reutilizáveis (`FlatComboButton`, profiles trees, graph widgets, vendor reference).
   - `cetuslib/main.py` — entrypoint da aplicação.
   - `cetuslib/utils.py` — funções utilitárias e classes TFTP.
   - `cetuslib/legacy.py` — monólito intermediário com o restante do código enquanto a extração continua.
   - Essa divisão agrupa responsabilidades e reduz o número de imports cruzados.

2. **Bundler: concatenação com cabeçalhos preservando ordem**
   - Script `scripts/bundle-monolith.py` lê módulos na ordem correta de dependência e grava `dist/cetus`.
   - A ordem é codificada no script para evitar imports circulares no arquivo único.
   - O arquivo gerado não usa imports relativos; todas as definições estão no escopo global do módulo, como hoje.
   - Imports internos `from cetuslib...` são removidos durante o bundle porque os símbolos já estão no escopo global.

3. **Entrypoint híbrido temporário**
   - O executável `cetus` na raiz, durante a transição, importará o pacote `cetuslib.main` e chamará `main()`.
   - Isso permite rodar direto do source sem reempacotar, acelerando desenvolvimento.
   - O pacote também pode ser executado via `python -m cetuslib`.
   - Quando o bundler for maduro, o `cetus` raiz passará a ser o artefato gerado em `dist/cetus`.

4. **Uso de `__all__` e imports explícitos**
   - Cada módulo expõe via `__all__` apenas o que outros módulos precisam.
   - Reduz acoplamento e deixa claro o contrato entre módulos.

5. **Faseamento**
   - Fase 1: criar pacote e mover classes sem alterar o arquivo `cetus` original (duplicação temporária).
   - Fase 2: fazer o `cetus` raiz importar do pacote e validar.
   - Fase 3: implementar bundler e validar que o arquivo gerado é idêntico em comportamento.
   - Fase 4: atualizar scripts de packaging e remover duplicação.

## Risks / Trade-offs

- [Risco] Dependências circulares dificultam a separação → Mitigação: identificar e quebrar ciclos movendo interfaces/constantes para `cetus/constants.py` ou `cetus/utils.py`.
- [Risco] Bundler gerar arquivo com ordem errada → Mitigação: validar via `py_compile` e teste de execução mínima após cada build.
- [Risco] Perda de histórico Git em movimentações grandes → Mitigação: mover código com `git mv` quando possível e fazer commits pequenos por módulo.
- [Trade-off] Arquivo `cetus` raiz passa a ser gerado, não editado → Mitigação: documentar claramente que edições devem ocorrer em `cetuslib/`.

## Migration Plan

1. Criar estrutura `cetuslib/`.
2. Mover classes/funções módulo a módulo, mantendo `cetuslib/legacy.py` como monólito intermediário.
3. Implementar `scripts/bundle-monolith.py`.
4. Alterar `cetus` raiz para importar do pacote.
5. Atualizar `scripts/make-deb.sh` e AppImage para executar o bundler antes do build.
6. Quando estável, remover `cetuslib/legacy.py` e tornar `cetus` um artefato gerado.

## Open Questions

- Qual a melhor ordem de movimentação para minimizar dependências circulares? (responder na fase de análise prévia)
- Os widgets de gráficos devem ficar em `cetus/ui/` ou junto com seus workers/domínios?
- Será necessário um arquivo `cetus/constants.py` separado para `BANNER_COLORS`, `VERSION`, etc.?
