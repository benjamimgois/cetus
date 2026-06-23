# Purpose

Define a divisão do código-fonte do Cetus em módulos temáticos dentro do pacote `cetuslib/`, preservando comportamento e eliminando dependências circulares.

## Requirements

### Requirement: Código-fonte dividido em módulos temáticos
O sistema SHALL organizar o código-fonte do Cetus em módulos Python dentro de um pacote `cetuslib/`, agrupados por responsabilidade.

#### Scenario: Estrutura de módulos existente
- **WHEN** um desenvolvedor inspeciona o repositório
- **THEN** o código está dividido em arquivos como `cetuslib/config.py`, `cetuslib/terminal.py`, `cetuslib/workers.py`, `cetuslib/network.py`, `cetuslib/ui/*.py`, `cetuslib/main.py` e `cetuslib/utils.py`

### Requirement: Sem alteração de comportamento
O sistema SHALL manter o comportamento do aplicativo inalterado após a modularização.

#### Scenario: Funcionalidade preservada
- **WHEN** o aplicativo é executado a partir dos módulos ou do arquivo monolítico gerado
- **THEN** todas as funcionalidades (SSH, Telnet, Serial, scan, Wi-Fi, transferência) continuam operando como antes

### Requirement: Remoção de dependências circulares
O sistema SHALL garantir que não existam imports circulares entre módulos do pacote `cetuslib/`.

#### Scenario: Importação de qualquer módulo
- **WHEN** qualquer módulo de `cetuslib/` é importado individualmente
- **THEN** a importação ocorre sem `ImportError` ou `circular import`
