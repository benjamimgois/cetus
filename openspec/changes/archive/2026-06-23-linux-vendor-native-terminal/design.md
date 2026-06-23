## Context

O Cetus mantém um emulador de terminal customizado baseado em `pyte` (`TerminalWidget`) embutido em `TerminalDialog`. Ele é usado para todas as sessões SSH, Telnet e Serial. Para ativos de rede esse emulador é suficiente, mas para hosts Linux aplicações interativas (`nano`, `vim`, `htop`, `mc`) que dependem de redimensionamento, teclas de função e escape sequences avançadas apresentam falhas de renderização e edição.

A solução é detectar o vendor `linux` e delegar a execução para o emulador de terminal nativo do sistema, mantendo o terminal customizado para os demais casos.

## Goals / Non-Goals

**Goals:**
- Abrir sessões SSH/Telnet/Serial para vendor `linux` no terminal nativo do sistema.
- Preservar o terminal customizado para vendors de rede.
- Permitir ao usuário escolher o comportamento por perfil.
- Implementar fallback automático para o terminal customizado quando não houver terminal nativo disponível.
- Suportar os principais emuladores: `konsole`, `gnome-terminal`, `xfce4-terminal`, `terminator`, `alacritty`, `kitty`, `xterm`.

**Non-Goals:**
- Reescrever o emulador customizado.
- Suportar Windows/macOS nativamente.
- Substituir o terminal customizado como padrão global.
- Persistir histórico/sessão do terminal nativo dentro do Cetus.

## Decisions

1. **Usar `QProcess` para lançar o terminal nativo**
   - Permite abrir o processo sem bloquear a GUI.
   - Simplifica detecção de erro e fallback.

2. **Critério de vendor `linux` insensível a maiúsculas/minúsculas**
   - Vendors podem vir como `"Linux"`, `"linux"` etc.
   - Normalizar para `linux` no momento da comparação.

3. **Preferência configurável por perfil (default automático)**
   - Opções: `auto` (usa native se vendor linux), `native`, `custom`.
   - Mantém flexibilidade sem forçar decisão rígida.

4. **Argumentos específicos por emulador**
   - Cada terminal usa flag diferente para executar comando (`-e`, `--`, etc.).
   - Mapear em dicionário interno e testar disponibilidade via `shutil.which`.

5. **Não reutilizar `TerminalDialog` para native terminal**
   - O processo roda independente; não há integração visual no Cetus.

## Risks / Trade-offs

- [Risco] Terminal nativo não trata redimensionamento automático fora do Cetus → Mitigação: usuário redimensiona manualmente; fora do escopo.
- [Risco] Dependência de emulador instalado → Mitigação: fallback para custom.
- [Risco] Perda de funcionalidades como scrollback e busca integradas → Mitigação: opt-in por perfil; custom continua disponível.
- [Trade-off] Processo filho pode continuar se o Cetus for fechado → Mitigação: usar `QProcess` com detachment opcional; documentar.
