# Proposal: add-automation-module

## Why

Executar a mesma sequência de comandos em dezenas/centenas de equipamentos de rede hoje exige scripts Python ad-hoc (ex.: `huawe_massconfig.py`), com credenciais hardcoded, sleeps cegos e resultados em texto no terminal. Isso é propenso a erro, não auditável e inacessível a quem não programa. Um módulo de automação dentro do Cetus resolve isso com UI, logs por host e detecção de sucesso confiável.

## What Changes

- Nova aba "Automation" na barra vertical de tabs (índice 9), seguindo o padrão existente de `QStackedWidget` + botões de ícone.
- Formulário de execução em massa:
  - Lista de alvos aceitando IP único, range de último octeto (`192.168.15.1-45`) e range completo (`10.0.0.1-10.0.0.45`), 1 entrada por linha, com dedupe e cap de segurança.
  - Campos usuário/senha (senha mascarada) com checkbox "Lembrar" (persistência via ConfigManager, mesmo mecanismo base64 dos perfis existentes).
  - Combobox de tipo de conexão (SSH/Telnet) com porta auto-preenchida (22/23) e editável.
  - Combobox de vendor com "Autodetect" como padrão e seleção manual (Huawei VRP, Cisco IOS, MikroTik RouterOS, Juniper JunOS, Genérico).
  - Textarea de comandos (1 por linha, `#` ignorado como comentário).
  - Configuração visual de timing: sleep entre comandos (default 1,0 s, espera mínima) e timeout por comando (default 30 s).
  - Modo de execução Serial (fila ordenada) ou Paralelo (pool configurável 2-20, default 5).
- Execução via workers em background (QThread) seguindo o padrão do projeto; wait-for-prompt como conclusão real de cada comando, com mapa interativo por vendor (pergunta → resposta automática, ex. `[Y/N]` → `Y`) — opção A, mapa fixo hardcoded.
- Tabela de resultados por host: IP, duração, status (Pendente/Executando/OK/Erro/Timeout/Cancelado) e mensagem, com cores.
- Logs por host salvos automaticamente em `~/.local/share/cetus/automation/<timestamp>/<ip>.log` + `run.json` (metadados da execução); duplo-clique na linha abre visualizador de log read-only com botão "Salvar como…".
- Botão de execução que vira contador de tempo/progresso durante a execução (`⏹ 00:01:23 · 12/51`) e funciona como botão Parar.

## Capabilities

### New Capabilities
- `automation`: Automação de comandos em massa em equipamentos de rede — entrada de alvos (ranges), credenciais, seleção de conexão/vendor, execução serial/paralela com wait-for-prompt e mapa interativo, tabela de status e logs por host.

### Modified Capabilities

Nenhum. Nenhum requisito existente muda; a aba nova é aditiva.

## Impact

- **Código novo**: `cetuslib/automation.py` (widget da aba + LogViewerDialog), `cetuslib/automation_worker.py` (AutomationManager + worker por host), `cetuslib/vendors.py` (regexes de prompt, erro e mapa interativo por vendor).
- **Código modificado**: `cetuslib/main.py` — registro da tab (botão de ícone, página no `QStackedWidget`, índice 9 em `switch_tab()`, entrada no dict `modes`).
- **Assets**: ícone SVG para a tab em `assets/icons/`.
- **Dependências**: nenhuma nova (paramiko e standard-telnetlib já usados).
- **Config**: novas chaves em `ConfigManager` para credenciais lembradas e último estado do formulário (opcional).
- **Empacotamento**: `dist/cetus` regenerado via `scripts/bundle-monolith.py`; nada muda nas receitas de .deb/AppImage/Flatpak.
- **Segurança**: senha persistida em base64 quando "Lembrar" marcado — mesma limitação conhecida dos perfis SSH, a documentar no README.
