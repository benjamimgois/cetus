# Purpose

Define como o Cetus abre sessões SSH/Telnet/Serial em terminal nativo do sistema quando o vendor do perfil é Linux, mantendo o terminal customizado para outros vendors.

## Requirements

### Requirement: Detect vendor Linux
O sistema SHALL detectar que o vendor do perfil de conexão é `linux` de forma case-insensitive.

#### Scenario: Vendor com letras maiúsculas
- **WHEN** o vendor do perfil é `"Linux"`
- **THEN** o sistema o trata como vendor `linux`

#### Scenario: Vendor com letras minúsculas
- **WHEN** o vendor do perfil é `"linux"`
- **THEN** o sistema o trata como vendor `linux`

### Requirement: Abrir terminal nativo para vendor Linux
O sistema SHALL abrir a sessão SSH/Telnet/Serial em um terminal nativo do sistema quando o vendor for `linux` e a preferência do perfil for `auto` ou `native`.

#### Scenario: Conexão SSH com vendor Linux
- **WHEN** o usuário inicia uma conexão SSH com vendor `linux` e preferência `auto`
- **THEN** o sistema lança o emulador de terminal nativo com o comando `ssh user@host`

#### Scenario: Conexão Telnet com vendor Linux
- **WHEN** o usuário inicia uma conexão Telnet com vendor `linux` e preferência `auto`
- **THEN** o sistema lança o emulador de terminal nativo com o comando `telnet host`

#### Scenario: Conexão Serial com vendor Linux
- **WHEN** o usuário inicia uma conexão Serial com vendor `linux` e preferência `auto`
- **THEN** o sistema lança o emulador de terminal nativo com o comando apropriado (por exemplo, `picocom`)

### Requirement: Manter terminal customizado para outros vendors
O sistema SHALL usar o `TerminalDialog`/`TerminalWidget` customizado quando o vendor não for `linux` ou quando a preferência for `custom`.

#### Scenario: Conexão Cisco com preferência auto
- **WHEN** o usuário inicia uma conexão com vendor `cisco` e preferência `auto`
- **THEN** o sistema abre o terminal customizado do Cetus
