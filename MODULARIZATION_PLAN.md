Plano de Modularização do Cetus
Visão Geral
Este plano descreve a quebra do arquivo monolítono cetus (26.807 linhas) em módulos lógicos e bem definidos para melhorar a manutenibilidade, legibilidade e organização do código.
Componentes Identificados para Separação
1. tftp_server.py - Funcionalidade TFTP completa
   - TFTPHandler (classe)
   - TFTPServer (classe)  
   - run_tftp_server_standalone (função)
2. secure_storage.py - Criptografia e gerenciamento de credenciais
   - Classe SecureStorage
   - Funções encrypt_password/decrypt_password
   - Gerenciamento de chaves com fallbacks
3. terminal_widget.py - Widget do terminal e rendering
   - TerminalWidget (classe principal)
   - _CursorOverlay (classe interna)
   - Delegates customizados (_AcItemDelegate, _TopCmdsDelegate)
   - Métodos de rendering e manipulação de texto
4. network_tools.py - Funções de rede puras
   - get_network_interfaces()
   - Utilidades de IP e rede sem dependências Qt
5. config_manager.py - Gerenciamento de configurações
   - ConfigManager (classe)
   - Persistência XDG Base Directory
   - Gerenciamento de perfis SSH/serial/SNMP
6. ui_components.py - Componentes de interface reutilizáveis
   - FlatComboButton (classe customizada)
   - Outros widgets customizados e delegates
   - Funções de utilidade de UI (load_svg_*, etc.)
7. protocol_workers.py - Workers QThread para protocolos
   - ScanWorker, ConnectionWorker, TracerouteWorker
   - NmapDiscoverWorker, MtrWorker, PingWorker
   - Iperf3Worker, SpeedTestWorker, etc.
   - Workers de transferência de arquivo (FileConnectWorker, etc.)
8. dialogs.py - Diálogos modais
   - StickyNoteDialog
   - VendorReferenceDialog
   - VendorConfigTemplateDialog
   - FileTextEditor e outros diálogos
9. main_window.py - Classe principal da GUI
   - SerialTerminalGUI (classe principal)
   - Funções de inicialização e setup da UI
   - Orquestração dos componentes
10. utils.py - Funções utilitárias puras
    - load_svg_pixmap, load_svg_icon, load_svg_icon_dual
    - Funções de formatação e conversão
    - Helpers sem dependências Qt pesadas
Estrutura de Diretórios Proposta
cetus/
├── cetus.py              # Arquivo principal reduzido (orquestração)
├── modules/
│   ├── __init__.py
│   ├── tftp_server.py
│   ├── secure_storage.py
│   ├── terminal_widget.py
│   ├── network_tools.py
│   ├── config_manager.py
│   ├── ui_components.py
│   ├── protocol_workers.py
│   ├── dialogs.py
│   ├── main_window.py
│   └── utils.py
├── assets/                  # Recursos existentes (ícones, SVGs, etc.)
├── build-anylinux/          # Diretórios de build existentes
├── packaging/               # Scripts de empacotamento
└── scripts/                 # Scripts auxiliares
Limites Claros para Cada Módulo
tftp_server.py
- Responsabilidade: Apenas funcionalidade TFTP (servidor/handler)
- Limites: Não deve conter código de GUI, terminal ou outros protocolos
- Dependências: socketserver, threading, os, pathlib
secure_storage.py
- Responsabilidade: Criptografia e gerenciamento seguro de credenciais
- Limites: Focado exclusivamente em segurança de dados
- Dependências: cryptography (opcional), os, json, base64, pathlib
terminal_widget.py
- Responsabilidade: Widget do terminal e funcionalidades de rendering
- Limites: Deve conter apenas o widget terminal e classes diretamente relacionadas
- Exclusões: Diálogos, workers de protocolo, configuração
- Dependências: PyQt6, pyte, threading
network_tools.py
- Responsabilidade: Funções de rede puras e utilitárias
- Limites: Zero dependências Qt ou GUI
- Exclusões: Qualquer código relacionado à interface gráfica
- Dependências: socket, ipaddress, threading, subprocess, re
config_manager.py
- Responsabilidade: Gerenciamento completo de configurações da aplicação
- Limites: Persistência, carregamento, salvamento e validação de settings
- Exclusões: Lógica de negócio ou renderização
- Dependências: json, os, pathlib, threading (para thread-safety se necessário)
ui_components.py
- Responsabilidade: Componentes de interface reutilizáveis e customizados
- Limites: Widgets que podem ser usados em múltiplas partes da aplicação
- Exclusões: Telas completas ou diálogos modais
- Dependências: PyQt6 (apenas componentes leves)
protocol_workers.py
- Responsabilidade: Implementação de workers QThread para protocolos de rede
- Limites: Apenas classes que herdam de QThread/QObject para trabalho em background
- Exclusões: Lógica de GUI ou renderização direta
- Dependências: PyQt6, protocolos específicos (paramiko, pysnmp, etc.)
dialogs.py
- Responsabilidade: Implementação de todos os diálogos modais da aplicação
- Limites: Classes que herdam de QDialog ou QWidget para popups
- Exclusões: Widgets principais da interface ou workers
- Dependências: PyQt6
main_window.py
- Responsabilidade: Classe principal da aplicação e ponto de entrada da GUI
- Limites: Orquestração de componentes, setup da UI principal
- Exclusões: Implementação detalhada de componentes (deve importar dos módulos)
- Dependências: PyQt6, todos os outros módulos
utils.py
- Responsabilidade: Funções utilitárias puras e ajudantes
- Limites: Funções independentes que não pertencem a nenhum domínio específico
- Exclusões: Classes complexas ou estado mutável
- Dependências: Bibliotecas padrão do Python (mínimas dependências externas)
Implementação Recomendada (Faseada)
Fase 1: Módulos Independentes
1. secure_storage.py (já implementado)
2. network_tools.py
3. utils.py
4. tftp_server.py
Fase 2: Componentes de Base
5. config_manager.py
6. ui_components.py
Fase 3: Workers e Lógica de Negócio
7. protocol_workers.py
8. terminal_widget.py
Fase 4: Interface e Integração
9. dialogs.py
10. main_window.py
11. cetus.py (arquivo principal reduzido)
Benefícios Esperados
1. Manutenibilidade: Arquivos menores e focados são mais fáceis de entender e modificar
2. Reutilização: Componentes podem ser reutilizados ou testados isoladamente
3. Colaboração: Desenvolvedores podem trabalhar em módulos diferentes simultaneamente
4. Testabilidade: Facilita criação de testes unitários para módulos específicos
5. Legibilidade: Estrutura clara reduz a carga cognitiva ao navegar pelo código
6. Compilação Mais Rápida: Mudanças em um módulo não requerem reparse do arquivo inteiro
Considerações de Implementação
- Manter compatibilidade total com a funcionalidade existente durante todo o processo
- Usar importações relativas dentro do pacote modules quando apropriado
- Manter o arquivo cetus.py como ponto de entrada que inicializa a aplicação
- Garantir que todas as dependências entre módulos sejam explícitas e bem definidas
- Considerar criar uma interface pública clara para cada módulo (funções/classes expostas)
- Documentar responsabilidades e limites de cada módulo em docstrings
