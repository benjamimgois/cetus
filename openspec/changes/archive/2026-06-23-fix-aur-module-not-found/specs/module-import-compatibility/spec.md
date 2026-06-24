## MODIFIED Requirements

### Requirement: Execução via pacote
O sistema SHALL permitir executar o Cetus a partir do pacote `cetuslib/` sem depender do arquivo monolítico.

#### Scenario: Execução como módulo
- **WHEN** o comando `python -m cetuslib` é executado na raiz do repositório
- **THEN** a interface gráfica é iniciada normalmente

### Requirement: Entrypoint híbrido durante transição
O sistema SHALL manter o arquivo `cetus` raiz funcional durante a transição, importando do pacote `cetuslib/`, e SHALL garantir que o launcher instalado via AUR também resolva o pacote.

#### Scenario: Execução do arquivo raiz
- **WHEN** o arquivo `./cetus` na raiz do repositório é executado
- **THEN** ele importa e inicia o aplicativo a partir do pacote `cetuslib/`

#### Scenario: Execução do launcher AUR
- **WHEN** o comando `cetus` é executado após instalação pelo AUR
- **THEN** o launcher em `/usr/bin/cetus` encontra e importa `cetuslib` de `/usr/share/cetus/cetuslib`

### Requirement: Símbolos exportados explicitamente
O sistema SHALL usar `__all__` em cada módulo para definir quais símbolos são públicos.

#### Scenario: Importação pública de símbolos
- **WHEN** um módulo externo faz `from cetuslib.terminal import TerminalDialog`
- **THEN** `TerminalDialog` está disponível e listado em `cetuslib.terminal.__all__`
