# Purpose

Define a descoberta e seleção do emulador de terminal nativo disponível no sistema operacional, incluindo ordem de preferência, argumentos corretos e fallback.

## Requirements

### Requirement: Descoberta de emulador nativo
O sistema SHALL detectar qual emulador de terminal nativo está disponível no sistema operacional.

#### Scenario: Konsole disponível
- **WHEN** o comando `konsole` está no PATH
- **THEN** o sistema seleciona `konsole` como emulador nativo

#### Scenario: GNOME Terminal disponível
- **WHEN** o comando `gnome-terminal` está no PATH e `konsole` não está
- **THEN** o sistema seleciona `gnome-terminal` como emulador nativo

### Requirement: Ordem de preferência de emuladores
O sistema SHALL seguir uma ordem de preferência fixa na escolha do emulador: `konsole`, `gnome-terminal`, `xfce4-terminal`, `terminator`, `alacritty`, `kitty`, `xterm`.

#### Scenario: Múltiplos emuladores instalados
- **WHEN** `konsole` e `gnome-terminal` estão instalados
- **THEN** o sistema escolhe `konsole`

### Requirement: Argumentos corretos por emulador
O sistema SHALL construir o comando de lançamento usando os argumentos corretos para o emulador selecionado.

#### Scenario: Lançar comando no Konsole
- **WHEN** o emulador selecionado é `konsole`
- **THEN** o sistema executa `konsole -e <comando>`

#### Scenario: Lançar comando no GNOME Terminal
- **WHEN** o emulador selecionado é `gnome-terminal`
- **THEN** o sistema executa `gnome-terminal -- <comando>`

### Requirement: Fallback quando nenhum emulador está disponível
O sistema SHALL usar o terminal customizado quando nenhum emulador nativo for encontrado.

#### Scenario: Sem terminal nativo instalado
- **WHEN** nenhum emulador conhecido está no PATH
- **THEN** o sistema abre a sessão no terminal customizado e pode exibir aviso ao usuário
