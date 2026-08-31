# Design: add-automation-module

## Context

O Cetus já possui o padrão de abas laterais (botões de ícone em `QStackedWidget`, `switch_tab()` com índices hardcoded em `cetuslib/main.py:406`), workers em `QThread` com signals em `cetuslib/workers.py` (19 workers existentes) e um worker de conexão única SSH/Telnet (`ConnectionWorker`, workers.py:319) — este último serve sessões interativas, não lotes. `paramiko` e `standard-telnetlib` já são dependências. O módulo se inspira no script interno `huawe_massconfig.py` (sleeps cegos + `"success" in output`), corrigindo suas fragilidades com wait-for-prompt e logs por host.

Ver proposta (motivação) e specs (comportamento): `specs/automation/spec.md`.

## Goals / Non-Goals

**Goals:**

- Execução confiável de lotes de comandos com conclusão real (prompt) em vez de sleeps cegos.
- Suporte multivendor com autodetecção por prompt e seleção manual.
- Execução responsiva: UI nunca bloqueia, stop funciona em tempo de leitura de socket.
- Logs auditáveis por host, sobrevivem a crash.

**Non-Goals:**

- Edição/aprovação de configuração (dry-run, diff antes de aplicar).
- Agendamento de execuções (cron-like).
- Suporte a SNMP/NETCONF/RESTCONF como transporte.
- Persistência de runs antigas em UI (arquivos ficam em disco; reabrir na UI fica para depois).
- Criptografia real de senha (herda a limitação base64 dos perfis existentes).

## Decisions

### D1: Módulos novos em vez de crescer `main.py`
`cetuslib/automation.py` (widget da aba + `LogViewerDialog`), `cetuslib/automation_worker.py` (workers), `cetuslib/vendors.py` (regexes por vendor). `main.py` tem 14k linhas; o padrão de modularização já existe (`ui/`, `network.py`, `terminal.py`). Alternativa considerada: tudo em `main.py` como o resto das abas — descartada por custo de manutenção.

### D2: `vendors.py` como tabela declarativa
Cada vendor é um dict com: regex de prompt, regex de prompt de config, regexes de erro, mapa interativo (pergunta → resposta), sequência de login Telnet. Autodetect = testar regexes de prompt na ordem Huawei → Cisco → MikroTik → Juniper → Genérico.

```python
VENDORS = {
    'huawei':  {'prompt': r'^<[^>]+>\s*$|^<[^>]+>$', ...},
    'cisco':   {'prompt': r'^[^\s#>]+[#>]\s*$', ...},
    'mikrotik': {'prompt': r'^\[[^\]]+\] >\s*$', ...},
    'juniper': {'prompt': r'^[^\s>]+>\s*$', ...},
    'generic': {'prompt': r'[\r\n]\S+[#>$]\s*$', ...},
}
```

Alternativa considerada: resposta interativa configurável pelo usuário (opção B) — descartada na v1 por escopo; mapa fixo cobre `[Y/N]` → `Y`, `Password:` → segredo de enable (campo opcional futuro), `continue|overwrite?` → `Y`.

### D3: Conclusão por wait-for-prompt com espera mínima
Loop de leitura com timeout curto (0,2 s) acumulando buffer; comando "termina" quando o buffer fecha com prompt detectado. O sleep configurado (1,0 s padrão) é a espera mínima entre comandos; se o prompt demorar mais, a detecção domina. Timeout por comando (30 s) encerra com status Timeout. Alternativa considerada: sleep puro (script original) — descartada: não detecta conclusão real nem erros.

Detecção de prompt precisa distinguir eco do comando vs. prompt real: comparar última linha do buffer após cada leitura; descartar linhas que contêm o comando enviado.

### D4: Paralelismo com pool de threads dedicadas, não QThreadPool genérico
`AutomationManager` (QThread) coordena: expande alvos, cria `AutomationHostWorker` por host (thread própria, máx N semáforo — na prática serial = 1, paralelo = pool size), agrega sinais e emite eventos de linha para a UI. Por worker: conexão (`paramiko` SSH com `AutoAddPolicy`, consistente com o resto do app; `standard-telnetlib` com expect de `Username:/login:` → `Password:`). Alternativa: `QThreadPool` + `QRunnable` — viable, mas workers aqui têm estado rico (buffer, vendor, cancel flag) e o padrão do projeto é `QThread` por worker.

Cancelamento: flag compartilhada checada entre comandos e dentro do loop de leitura (timeout curto garante responsividade ≤ ~0,2 s). Canais em andamento são fechados. Pendentes → Cancelado.

### D5: Estados e sinalização
Signals do manager: `row_started(ip)`, `row_finished(ip, dur, status, msg, vendor)`, `progress(done, total)`, `finished()` — todos conectados a slots da UI (padrão do projeto; nunca tocar widget de dentro da thread). Status como enum/constantes: PENDING, RUNNING, OK, ERROR, TIMEOUT, CANCELLED.

### D6: Logs automáticos em `~/.local/share/cetus/automation/<timestamp>/`
Escrita incremental por worker (append após cada comando) — crash preserva o que já foi capturado. `run.json` escrito pelo manager ao final. Duplo-clique → `LogViewerDialog` (QPlainTextEdit read-only + cabeçalho de metadados + "Salvar como…"). Arquivo de log nomeado por IP sanitizado (IP é nome seguro; dedupe já garante umicidade).

### D7: Credenciais e persistência
Senha mascarada (`QLineEdit.Password`). Checkbox "Lembrar": marcado → usuário/senha em `ConfigManager` (base64, mesma limitação dos perfis SSH — documentar no README); desmarcado → não grava e limpa credenciais salvas. Alternativa: keyring do sistema — descartada na v1 (nova dependência; padrão do app é ConfigManager).

### D8: Validação e cap de segurança
Parser de alvos: linha = IP | último-octeto-range | range completo; expande, dedupe (preserva ordem), rejeita inválidos com aviso listando as linhas problemáticas. Cap 1024 alvos → diálogo de confirmação. Comandos: linhas `#` são comentários; linhas vazias ignoradas.

### D9: Registro da aba (índice 9)
Botão de ícone SVG em `assets/icons/` (novo, `automation.svg`), página no `content_stack`, índice 9 em `switch_tab()` e dict `modes` (`'automation'`). Segue exatamente o padrão das 9 abas existentes.

## Risks / Trade-offs

- [Prompt multivendor tem falsos positivos — Juniper `user@host>` colide com Cisco user-exec] → ordem de teste dos regexes da mais específica pra menos (MikroTik → Huawei → Juniper → Cisco → Genérico) e vendor manual como escape.
- [Telnet: banners e ritmo de login variam por vendor/firmware] → expect com timeouts generosos (10 s) por etapa de login; falha = status Erro com etapa na mensagem.
- [Comandos que geram output longo (ex.: `display current-configuration`) podem ultrapassar timeout de 30 s] → timeout configurável por execução; documentar no cabeçalho da aba.
- [Senha em base64 quando "Lembrar"] → mesma limitação conhecida dos perfis; README já deve/documenta; nunca persistir quando desmarcado.
- [Stop em `time.sleep` longo no meio de um comando] → sleeps nunca superam o timeout de leitura (implementar espera como acumulador de leituras de 0,2 s checando cancel flag).
- [Picos de conexão em pool alto contra uma mesma subrede] → pool default 5, máx 20; cap global de 1024 alvos.
- [`AutoAddPolicy` aceita host keys desconhecidos] → consistente com o resto do Cetus (MITM risk herdado, já conhecido do projeto).

## Migration Plan

Sem migração de dados. Deploy = adicionar módulos + registro da aba + regenerar `dist/cetus` (`python3 scripts/bundle-monolith.py`). Rollback = remover os arquivos novos e reverter o registro da aba em `main.py` — nada existente muda de comportamento.

## Open Questions

Nenhuma. Escopo fechado na exploração (mapa interativo opção A, execução serial/paralelo selecionável, logs por host).
