# Purpose

Define o gerador de arquivo monolítico `dist/cetus` a partir dos módulos `cetuslib/`, garantindo equivalência com a execução via pacote e integração nos scripts de packaging.

## Requirements

### Requirement: Gerar arquivo monolítico para distribuição
O sistema SHALL fornecer um script capaz de concatenar os módulos do pacote `cetuslib/` em um único arquivo executável, preservando a ordem de dependências.

#### Scenario: Execução do bundler
- **WHEN** o script `scripts/bundle-monolith.py` é executado
- **THEN** um arquivo `dist/cetus` é gerado e é sintaticamente válido

### Requirement: Arquivo gerado equivalente ao pacote
O sistema SHALL garantir que o arquivo monolítico gerado tenha o mesmo comportamento do pacote `cetuslib/`.

#### Scenario: Comportamento idêntico
- **WHEN** o arquivo `dist/cetus` gerado é executado
- **THEN** o aplicativo inicia e responde da mesma forma que a execução via `python -m cetuslib`

### Requirement: Integração com scripts de packaging
O sistema SHALL invocar o bundler nos scripts de build Debian e AppImage antes de empacotar.

#### Scenario: Build Debian
- **WHEN** o script `scripts/make-deb.sh` é executado
- **THEN** o bundler é chamado e o arquivo `cetus` gerado é incluído no pacote

#### Scenario: Build AppImage
- **WHEN** o script `scripts/make-anylinux-appimage.sh` é executado
- **THEN** o bundler é chamado antes da montagem da AppImage
