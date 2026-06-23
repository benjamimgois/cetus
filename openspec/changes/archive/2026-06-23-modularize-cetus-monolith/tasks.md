## 1. Análise e preparação

- [x] 1.1 Mapear classes e funções do arquivo `cetus` por responsabilidade e identificar dependências circulares.
- [x] 1.2 Definir a lista final de módulos e a ordem de importação entre eles.
- [x] 1.3 Criar diretório `cetuslib/` com `__init__.py` vazio e esqueleto dos módulos.

## 2. Extração de módulos

- [x] 2.1 Mover `ConfigManager` e configurações para `cetuslib/config.py`.
- [x] 2.2 Mover widgets do terminal (`TerminalWidget`, `TerminalDialog`, `TerminalTabbedWindow`, etc.) para `cetuslib/terminal.py`.
- [x] 2.3 Mover workers `QThread` (ConnectionWorker, ScanWorker, MtrWorker, etc.) para `cetuslib/workers.py`.
- [x] 2.4 Mover funcionalidades de rede (scanner, Wi-Fi, iperf3, traceroute, nmap) para `cetuslib/network.py`.
- [x] 2.5 Mover transferência de arquivos (SFTP, FTP, SMB) para `cetuslib/workers.py`/`cetuslib/main.py` (sem módulo `transfer.py` separado).
- [x] 2.6 Mover widgets reutilizáveis (árvores de perfil, referência de vendor, editor) para `cetuslib/ui/`.
- [x] 2.7 Mover `SerialTerminalGUI` e entrypoint para `cetuslib/main.py`.
- [x] 2.8 Mover funções utilitárias e TFTP para `cetuslib/utils.py`.

## 3. Quebra de dependências circulares

- [x] 3.1 Criar `cetuslib/constants.py` para constantes compartilhadas (`VERSION`, etc.).
- [x] 3.2 Refatorar imports para eliminar ciclos entre os módulos extraídos.
- [x] 3.3 Verificar que cada módulo pode ser importado isoladamente sem `circular import`.

## 4. Entrypoint e compatibilidade

- [x] 4.1 Implementar `cetuslib/main.py` com função `main()` que inicia a aplicação.
- [x] 4.2 Alterar o arquivo `cetus` raiz para importar e executar `cetuslib.main.main()`.
- [x] 4.3 Garantir que `python -m cetuslib` funcione a partir da raiz do repositório.

## 5. Bundler monolítico

- [x] 5.1 Criar `scripts/bundle-monolith.py` que lê os módulos na ordem correta.
- [x] 5.2 Fazer o bundler substituir imports relativos por definições concatenadas no escopo global.
- [x] 5.3 Gerar arquivo `dist/cetus` via bundler e validar com `python3 -m py_compile dist/cetus`.
- [x] 5.4 Comparar comportamento do arquivo gerado com execução via pacote.

## 6. Atualização de builds

- [x] 6.1 Atualizar `debian/rules` para gerar `dist/cetus` via bundler durante o build do .deb.
- [x] 6.2 Atualizar `scripts/make-anylinux-appimage.sh` para gerar `dist/cetus` antes do build.
- [x] 6.3 Verificar que os artefatos .deb e AppImage gerados contêm o `cetus` atualizado (scripts validados via análise estática e bundle testado; builds reais não executados por falta de dpkg-deb/quick-sharun).

## 7. Limpeza e documentação

- [x] 7.1 Remover código duplicado: `cetuslib/legacy.py` reduzido ao stub TFTP; `cetus` raiz é launcher.
- [x] 7.2 Atualizar `README.md` e `AGENTS.md` com instruções de desenvolvimento no novo layout.
- [x] 7.3 Adicionar `.gitignore` para ignorar o `dist/` gerado pelo bundler.
