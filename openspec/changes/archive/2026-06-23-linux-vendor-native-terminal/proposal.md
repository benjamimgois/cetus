## Why

O emulador de terminal VT100/ANSI customizado do Cetus funciona bem para ativos de rede, mas apresenta problemas de renderização e edição quando usado para acessar hosts Linux (por exemplo, ao editar arquivos com `nano`, `vim` ou `mc`). Para hosts Linux, o terminal nativo do sistema operacional (Konsole, GNOME Terminal, etc.) oferece compatibilidade completa com aplicações interativas e evita a necessidade de manter um emulador perfeito nesses casos.

## What Changes

- Adicionar um novo comportamento de abertura de sessão SSH/Telnet/Serial para hosts cujo *vendor* seja `linux`.
- Quando o vendor for `linux`, o Cetus abrirá o terminal padrão do sistema (`konsole`, `gnome-terminal`, `xfce4-terminal`, `terminator` etc.) via `QProcess`, em vez de usar o `TerminalWidget`/`TerminalDialog` customizado.
- Manter o terminal customizado como padrão para todos os demais vendors (Cisco, Huawei, MikroTik, Juniper, etc.).
- Criar um mecanismo configurável (settings + checkbox no diálogo de conexão/perfis) para permitir forçar o uso do terminal nativo ou do customizado por perfil.
- Garantir fallback para o terminal customizado caso nenhum terminal nativo seja encontrado no sistema.

## Capabilities

### New Capabilities

- `linux-vendor-terminal-launch`: Detecção de vendor `linux` e abertura de sessão SSH/Telnet/Serial em terminal nativo do sistema.
- `terminal-launch-preference`: Preferência configurável por perfil para escolher entre terminal nativo e terminal customizado.
- `native-terminal-discovery`: Descoberta e seleção do emulador de terminal nativo disponível (Konsole, GNOME Terminal, etc.).

### Modified Capabilities

- (nenhum — requisitos de outras capabilities não mudam, apenas a implementação)

## Impact

- Código: `cetus` (principalmente lógica de abertura de conexão e diálogo de perfis), `ConfigManager` (nova chave de preferência), e possivelmente `VendorConfigTemplateDialog`.
- Experiência do usuário: melhora edição interativa em hosts Linux; comportamento padrão muda apenas para vendor `linux`.
- Dependências externas: requer que pelo menos um emulador de terminal padrão esteja instalado; fallback manter compatibilidade.
