## ADDED Requirements

### Requirement: Preferência de terminal por perfil
O sistema SHALL permitir configurar, por perfil de conexão, se a sessão será aberta no terminal nativo ou no terminal customizado.

#### Scenario: Preferência padrão auto
- **WHEN** um novo perfil é criado
- **THEN** a preferência de terminal é `auto`

### Requirement: Valores válidos de preferência
O sistema SHALL aceitar apenas os valores `auto`, `native` e `custom` para a preferência de terminal.

#### Scenario: Seleção de preferência native
- **WHEN** o usuário altera a preferência do perfil para `native`
- **THEN** todas as sessões desse perfil são abertas no terminal nativo, independentemente do vendor

#### Scenario: Seleção de preferência custom
- **WHEN** o usuário altera a preferência do perfil para `custom`
- **THEN** todas as sessões desse perfil são abertas no terminal customizado, independentemente do vendor

### Requirement: Persistência da preferência
O sistema SHALL salvar a preferência de terminal no perfil e restaurá-la ao carregar o perfil.

#### Scenario: Recarregar perfil
- **WHEN** o aplicativo é reiniciado
- **THEN** a preferência de terminal de cada perfil é carregada corretamente
