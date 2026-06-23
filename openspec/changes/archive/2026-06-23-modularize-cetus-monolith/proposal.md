## Why

O arquivo `cetus` cresceu para ~29k linhas e ~50 classes, dificultando navegação, revisões e manutenção. Segmentar o código em módulos temáticos reduz o contexto necessário para cada alteração, diminui o consumo de tokens em ferramentas de IA e facilita testes unitários, sem quebrar a distribuição como arquivo único que o projeto adota.

## What Changes

- Criar a estrutura de pacote `cetuslib/` com módulos por responsabilidade (config, terminal, workers, rede, UI, utilidades, etc.).
- Mover classes e funções do arquivo `cetus` para os módulos correspondentes.
- Criar um script de build que concatena os módulos em um único arquivo `cetus` para continuidade das embalagens AppImage, .deb e AUR.
- Manter o arquivo `cetus` raiz funcional durante a transição, importando do pacote.
- Atualizar scripts de build e CI para gerar o artefato monolítico a partir dos módulos.
- Garantir que não haja mudanças de comportamento para o usuário final.

## Capabilities

### New Capabilities

- `source-modularization`: Divisão do código-fonte em módulos temáticos dentro do pacote `cetus/`.
- `distribution-bundler`: Geração do arquivo executável único `cetus` a partir dos módulos via script de build.
- `module-import-compatibility`: Suporte à execução do Cetus tanto pelo pacote `cetus/` quanto pelo arquivo monolítico legado durante a transição.

### Modified Capabilities

- (nenhum — esta mudança não altera requisitos funcionais, apenas a organização do código)

## Impact

- Estrutura do repositório: novo diretório `cetuslib/` com módulos; `cetus` raiz vira entrypoint ou artefato gerado.
- Scripts de build/packaging (`scripts/make-deb.sh`, `make-anylinux-appimage.sh`, etc.) devem passar a invocar o bundler.
- Importações internas: remoção de dependências circulares e uso de imports relativos no pacote.
- Testes: possibilidade de testar módulos isoladamente.
- Nenhuma mudança na interface ou comportamento do aplicativo.
