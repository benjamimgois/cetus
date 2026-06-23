## 1. Configuração e persistência

- [x] 1.1 Adicionar chave `terminal_mode` (`auto`/`native`/`custom`) ao `ConfigManager.defaults` e garantir merge em perfis existentes.
- [x] 1.2 Atualizar `ConfigManager.save_ssh_profile` para aceitar e persistir `terminal_mode` no perfil SSH.
- [x] 1.3 Atualizar `ConfigManager.save_serial_profile` para aceitar e persistir `terminal_mode` no perfil serial.
- [x] 1.4 Atualizar carregamento de perfis (`load_ssh_profile_from_tree`, `load_serial_profile_from_tree`, `_connect_all_in_group`) para restaurar `terminal_mode` em `_pending_terminal_mode`.

## 2. Descoberta e lançamento do terminal nativo

- [x] 2.1 Criar helper `NativeTerminalLauncher` (ou funções em `SerialTerminalGUI`) que mapeie emuladores e argumentos: `konsole -e`, `gnome-terminal --`, `xfce4-terminal -e`, `terminator -e`, `alacritty -e`, `kitty -e`, `xterm -e`.
- [x] 2.2 Implementar `find_native_terminal()` que retorna o primeiro executável disponível via `shutil.which` na ordem de preferência.
- [x] 2.3 Implementar `build_terminal_command(emulator, base_command)` que retorne a lista de argumentos correta para o emulador detectado.
- [x] 2.4 Implementar `launch_native_terminal(command_list)` usando `QProcess`, com tratamento de erro e retorno booleano.

## 3. Decisão de caminho de execução

- [x] 3.1 Implementar `should_use_native_terminal(vendor, terminal_mode)` que retorna `True` quando `terminal_mode == 'native'` ou (`terminal_mode == 'auto'` e `vendor.lower() == 'linux'`).
- [x] 3.2 Em `SerialTerminalGUI.connect_ssh`, após validar credenciais, capturar `_pending_vendor` e `_pending_terminal_mode`; se `should_use_native_terminal` for `True`, construir o comando SSH/Telnet e chamar `launch_native_terminal`; senão, seguir fluxo atual com `ConnectionWorker`.
- [x] 3.3 Em `SerialTerminalGUI.connect()` (serial), após carregar perfil, aplicar a mesma decisão e lançar `picocom` no terminal nativo quando apropriado.

## 4. Interface do usuário

- [x] 4.1 Adicionar `QComboBox` "Terminal mode" (`Auto`/`Native`/`Custom`) ao diálogo `save_current_ssh_profile`, pré-selecionando o valor atual do perfil ou `Auto`.
- [x] 4.2 Ajustar a chamada `self.config.save_ssh_profile(...)` para incluir o `terminal_mode` escolhido.
- [x] 4.3 Adicionar seleção de `terminal_mode` ao fluxo de salvamento do perfil serial (`save_current_serial_profile`).
- [x] 4.4 (Opcional) Exibir ícone ou coluna "Terminal" na árvore de perfis para indicar modo `native`. *(opcional — não implementado)*

## 5. Fallback e validação

- [x] 5.1 Garantir fallback para o terminal customizado quando `find_native_terminal()` retornar `None`.
- [x] 5.2 Exibir `QMessageBox.warning` quando o usuário escolheu `native` mas nenhum emulador nativo foi encontrado.
- [x] 5.3 Garantir que `QProcess` não bloqueie a GUI e que o botão "CONNECT" volte ao estado normal após lançamento.

## 6. Testes e verificação

- [x] 6.1 Executar `python3 -m py_compile cetus` e corrigir erros de sintaxe.
- [x] 6.2 Testar perfil SSH com vendor `Linux` e modo `Auto` abrindo `konsole`/`gnome-terminal`.
- [x] 6.3 Testar perfil SSH com vendor `Cisco` mantendo o terminal customizado.
- [x] 6.4 Testar modo `Native` explícito com vendor não-Linux.
- [x] 6.5 Testar fallback removendo temporariamente os emuladores nativos do PATH.
