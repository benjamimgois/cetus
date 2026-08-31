# automation

## Purpose

Capacidade de executar comandos em massa em equipamentos de rede via SSH ou Telnet, com detecção de vendor, execução serial ou paralela, tabela de status por host e logs auditáveis por sessão.

## ADDED Requirements

### Requirement: Entrada de alvos com ranges
O sistema SHALL aceitar uma lista de alvos onde cada linha contém um IP único (`192.168.15.1`), um range de último octeto (`192.168.15.1-45`) ou um range completo (`10.0.0.1-10.0.0.45`), e SHALL expandir os ranges em endereços individuais antes da execução.

#### Scenario: Range de último octeto
- **WHEN** o usuário digita `192.168.15.1-3` na lista de alvos
- **THEN** a execução cobre `192.168.15.1`, `192.168.15.2` e `192.168.15.3`

#### Scenario: Range completo
- **WHEN** o usuário digita `10.0.0.5-10.0.0.7` na lista de alvos
- **THEN** a execução cobre `10.0.0.5`, `10.0.0.6` e `10.0.0.7`

#### Scenario: Endereços duplicados
- **WHEN** a expansão da lista produz endereços repetidos
- **THEN** cada endereço é executado uma única vez

#### Scenario: Limite de segurança
- **WHEN** a expansão da lista excede o limite máximo de alvos (1024)
- **THEN** a execução não inicia e o usuário é avisado antes de prosseguir

### Requirement: Credenciais de conexão
O sistema SHALL coletar usuário e senha para autenticação nos alvos, com a senha mascarada durante a digitação. Um checkbox "Lembrar" SHALL controlar se as credenciais são persistidas entre sessões.

#### Scenario: Senha mascarada
- **WHEN** o usuário digita a senha
- **THEN** os caracteres são exibidos como eco de senha e não aparecem em texto claro na UI

#### Scenario: Lembrar marcado
- **WHEN** o usuário executa com "Lembrar" marcado
- **THEN** usuário e senha são persistidos e pré-preenchidos na próxima abertura do aplicativo

#### Scenario: Lembrar desmarcado
- **WHEN** o usuário executa com "Lembrar" desmarcado
- **THEN** nenhuma credencial é gravada em disco e credenciais previamente salvas são descartadas

### Requirement: Tipo de conexão e porta
O sistema SHALL permitir escolher SSH ou Telnet e SHALL preencher a porta automaticamente (22 para SSH, 23 para Telnet) quando o tipo muda, permitindo edição manual da porta.

#### Scenario: Troca de tipo de conexão
- **WHEN** o usuário muda o combobox de SSH para Telnet
- **THEN** a porta muda de 22 para 23, ainda editável

### Requirement: Seleção de vendor
O sistema SHALL oferecer um combobox de vendor com "Autodetect" como padrão e opções manuais (Huawei VRP, Cisco IOS, MikroTik RouterOS, Juniper JunOS, Genérico). No modo Autodetect, o sistema SHALL inferir o vendor pelo padrão do prompt apresentado após o login.

#### Scenario: Autodetect reconhece Huawei
- **WHEN** o prompt da sessão após login corresponde ao padrão `<hostname>`
- **THEN** o vendor da sessão é Huawei VRP

#### Scenario: Vendor manual
- **WHEN** o usuário seleciona um vendor manualmente
- **THEN** todos os alvos da execução usam os padrões de prompt, erro e interatividade desse vendor

#### Scenario: Vendor não reconhecido
- **WHEN** o prompt após login não corresponde a nenhum vendor conhecido
- **THEN** a sessão usa os padrões genéricos e a mensagem da linha indica vendor desconhecido

### Requirement: Execução de comandos com wait-for-prompt
O sistema SHALL enviar cada comando da lista ao equipamento e aguardar a detecção do prompt (indício de conclusão) com timeout configurável por comando (padrão 30 s). O intervalo configurável entre comandos (padrão 1,0 s) SHALL ser tratado como espera mínima, não como alvo rígido.

#### Scenario: Conclusão por prompt
- **WHEN** um comando é enviado e o prompt reaparece antes do timeout
- **THEN** o próximo comando é enviado após o intervalo mínimo configurado

#### Scenario: Timeout de comando
- **WHEN** o prompt não reaparece dentro do timeout configurado
- **THEN** o comando é considerado estourado, a sessão é encerrada e a linha do host marca status de timeout

#### Scenario: Comentários ignorados
- **WHEN** a lista de comandos contém linhas iniciadas por `#`
- **THEN** essas linhas não são enviadas ao equipamento

### Requirement: Resposta automática a comandos interativos
O sistema SHALL responder automaticamente a perguntas interativas do equipamento usando um mapa fixo por vendor (ex.: confirmação `[Y/N]` → `Y`, aviso `Password:` → resposta configurada), sem exigir intervenção do usuário durante a execução.

#### Scenario: Confirmação de save
- **WHEN** o equipamento exibe uma pergunta de confirmação no formato `[Y/N]` durante a execução
- **THEN** o sistema responde automaticamente `Y` sem encerrar a sessão

### Requirement: Modo de execução serial e paralelo
O sistema SHALL permitir escolher entre execução serial (um alvo por vez, em ordem) e paralela (pool de conexões simultâneas configurável entre 2 e 20, padrão 5).

#### Scenario: Execução serial
- **WHEN** o modo serial está selecionado
- **THEN** os alvos são executados um por vez, na ordem da lista

#### Scenario: Execução paralela
- **WHEN** o modo paralelo está selecionado com pool de 5
- **THEN** até 5 alvos são executados simultaneamente, sem garantia de ordem entre eles

### Requirement: Tabela de status por host
O sistema SHALL exibir uma tabela com uma linha por alvo contendo endereço, duração da sessão, status e mensagem. Os status SHALL ser: Pending, Running, OK, Error, Timeout e Cancelled, com diferenciação visual por cor.

#### Scenario: Progressão de status
- **WHEN** a execução inicia e um host é conectado com sucesso
- **THEN** a linha do host muda de Pendente para Executando e, ao final, para OK, Erro ou Timeout

#### Scenario: Falha de autenticação
- **WHEN** o login em um host falha
- **THEN** a linha do host marca status Erro com a mensagem do motivo

### Requirement: Logs por host
O sistema SHALL salvar automaticamente o output capturado de cada host em arquivo de log por execução, sob `~/.local/share/cetus/automation/<timestamp>/`, incluindo um arquivo de log por host e metadados da execução (endereço, status, duração, vendor, mensagem). Um duplo-clique na linha da tabela SHALL abrir o log correspondente em visualizador read-only com opção de salvar em outro local.

#### Scenario: Log gerado automaticamente
- **WHEN** a execução de um host termina (em qualquer status)
- **THEN** um arquivo de log com o output capturado existe no diretório da execução

#### Scenario: Visualização do log
- **WHEN** o usuário dá duplo-clique em uma linha da tabela
- **THEN** o log do host abre em visualizador read-only, com cabeçalho de metadados e botão "Salvar como…"

#### Scenario: Metadados da execução
- **WHEN** a execução inteira termina
- **THEN** um arquivo de metadados da execução existe no mesmo diretório, com endereço, status, duração, vendor e mensagem de cada host

### Requirement: Controle de execução
O sistema SHALL disponibilizar um botão que inicia a execução e, durante a execução, exibe o tempo decorrido total e o progresso (hosts concluídos/total), funcionando também como botão de parada. Ao parar, as sessões em andamento SHALL ser interrompidas na próxima leitura e os alvos ainda não iniciados SHALL ser marcados como Cancelados.

#### Scenario: Início da execução
- **WHEN** o usuário clica no botão com alvos e comandos preenchidos
- **THEN** a execução inicia e o botão passa a exibir o tempo decorrido e o progresso

#### Scenario: Botão desabilitado sem alvos
- **WHEN** a lista de alvos ou a lista de comandos está vazia
- **THEN** o botão de execução não dispara a execução

#### Scenario: Parada da execução
- **WHEN** o usuário clica no botão durante a execução
- **THEN** as sessões ativas são interrompidas de forma responsiva, os alvos pendentes são marcados como Cancelados e o botão volta ao estado original

#### Scenario: Bloqueio de reconfiguração
- **WHEN** a execução está em andamento
- **THEN** os campos do formulário (alvos, credenciais, comandos, timing) não podem ser alterados
