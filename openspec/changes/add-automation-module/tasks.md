# Tasks: add-automation-module

## 1. Fundação — vendor e parsing

- [x] 1.1 Criar `cetuslib/vendors.py` com tabela declarativa por vendor (Huawei VRP, Cisco IOS, MikroTik RouterOS, Juniper JunOS, Genérico): regexes de prompt, prompt de config, erros, mapa interativo (`[Y/N]` → `Y`, `continue|overwrite?` → `Y`, `Password:`) e função de autodetect testando prompts na ordem de especificidade. Verificar com `python3 -m py_compile cetuslib/vendors.py` e teste manual das regexes contra prompts reais (`<SW1>`, `SW1#`, `[admin@MikroTik] >`, `user@jun>`)
- [x] 1.2 Implementar parser de alvos (IP único, range de último octeto `a.b.c.d-e`, range completo `a.b.c.d-x.y.z.w`), dedupe preservando ordem, lista de linhas inválidas e cap de 1024. Verificar com teste manual: `192.168.15.1-3` → 3 IPs, `10.0.0.5-10.0.0.7` → 3 IPs, duplicados colapsados, linha inválida reportada

## 2. Workers

- [x] 2.1 Criar `cetuslib/automation_worker.py` com `AutomationHostWorker` (QThread): conexão SSH (paramiko, `AutoAddPolicy`) e Telnet (standard-telnetlib, expect `Username:/login:` → `Password:`), loop de leitura com timeout de 0,2 s acumulando buffer, wait-for-prompt por comando, mapa interativo, cancel flag checada entre leituras e entre comandos. Verificar com `python3 -m py_compile cetuslib/automation_worker.py`
- [x] 2.2 Implementar captura de output e escrita incremental do log por host em `~/.local/share/cetus/automation/<timestamp>/<ip>.log`. Verificar executando contra host de teste e conferindo que o log cresce após cada comando
- [x] 2.3 Criar `AutomationManager` (QThread) que expande alvos, dispara workers (serial = 1, paralelo = pool 2-20), agrega e emite signals `row_started`, `row_finished`, `progress`, `finished`, escreve `run.json` ao final e responde ao stop fechando sessões ativas. Verificar com `python3 -m py_compile cetuslib/automation_worker.py`

## 3. UI

- [x] 3.1 Criar `cetuslib/automation.py` com `AutomationTab`: formulário (lista de alvos, usuário/senha mascarada + checkbox "Lembrar", combobox SSH/Telnet com porta auto 22/23 editável, combobox vendor com Autodetect default, textarea de comandos com `#` comentário, spinbox de sleep entre comandos default 1,0 s, timeout por comando default 30 s, modo Serial/Paralelo + pool 2-20 default 5) e tabela de resultados com colunas IP/duração/status/mensagem e cores por status. Verificar com `python3 -m py_compile cetuslib/automation.py` e abertura da aba no app
- [x] 3.2 Implementar controle de execução: botão que inicia e durante a execução exibe `⏹ 00:01:23 · 12/51` (QTimer), segundo clique = stop, campos do formulário desabilitados durante execução, botão desabilitado sem alvos ou comandos. Verificar executando lote pequeno e observando contador, stop e reabilitação dos campos
- [x] 3.3 Criar `LogViewerDialog` (QPlainTextEdit read-only com cabeçalho de metadados — host, início, duração, vendor, status — e botão "Salvar como…") conectado ao duplo-clique na tabela. Verificar com duplo-clique em linha concluída abrindo o log correto
- [x] 3.4 Persistir credenciais via ConfigManager quando "Lembrar" marcado (pré-preencher na próxima abertura) e descartar quando desmarcado. Verificar reiniciando o app com o checkbox marcado e depois desmarcado

## 4. Integração na janela principal

- [x] 4.1 Adicionar ícone `assets/icons/automation.svg` e registrar a aba em `cetuslib/main.py`: botão de ícone no layout lateral, página no `content_stack`, índice 9 em `switch_tab()` e entrada `'automation'` no dict `modes`. Verificar com `python3 -m py_compile cetuslib/main.py` e troca de aba pela UI
- [x] 4.2 Conectar signals do `AutomationManager` aos slots da tabela (padrão signals/slots, nenhum toque em widget de dentro de thread). Verificar com execução de lote contra 2-3 hosts reais e observação de atualização de linhas

## 5. Validação final

- [x] 5.1 Teste de integração: lote misto (hosts ok, host inexistente, senha errada, host lento) cobrindo status OK/Erro/Timeout/Cancelado, serial e paralelo, SSH e Telnet, autodetect e vendor manual. Verificar tabela, logs, `run.json` e responsividade do stop
- [x] 5.2 Regressão: `python3 -m py_compile cetuslib/main.py cetuslib/automation.py cetuslib/automation_worker.py cetuslib/vendors.py`, regenerar `dist/cetus` com `python3 scripts/bundle-monolith.py`, executar `./cetus` e verificar que as 9 abas existentes continuam funcionando
- [x] 5.3 Documentar no README: seção Automation (uso, range de alvos, vendors suportados, limitação da senha em base64 com "Lembrar"). Verificar leitura do README
