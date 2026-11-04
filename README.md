# keypassXD

Gerenciador de senhas **local** com aparência adaptada à paleta do Omarchy, ícones SVG e botão de **cadeado no topbar**. Projeto experimental versão 0.3.0. Cores sincronizadas com o tema ativo do Omarchy. **100% local em uso: sem conta, sem rede, sem telemetria; não requer KeePassXC instalado** (o formato `.kdbx` continua compatível com ele se um dia você quiser abrir por lá).

**Atenção:** esta implementação **não passou por auditoria de segurança**. Não migre todas as suas senhas reais para este protótipo sem revisão do código, testes no seu ambiente e backup verificado. Para guardar credenciais críticas desde já, o KeePassXC original é a escolha mais madura.

## O que faz

- Integra à barra do Omarchy por meio de `manifest.json` e `BarWidget.qml`: **cadeado (Nerd Font U+F023) via `BarIconButton`** na seção direita; só executa `launch.sh`, nenhuma senha passa pelo shell.
- Cofres novos usam **Argon2id (64 MiB, mínimo 3 iterações)** — padrão KeePassXC atual. Cofres antigos em Argon2d/AES-KDF **migram sozinhos para Argon2id no próximo save** (custo maior que o mínimo nunca é rebaixado). O rótulo `KDF:` na barra lateral mostra o algoritmo ativo.
- Abre um aplicativo separado em PySide6. A senha mestra **não** passa pelo QML nem pelo processo persistente do shell; a cópia Python é descartada (`del`) logo após o uso.
- 100% local verificado por teste (`tests/test_security.py`): nenhum `import` de rede em `app/`, nenhuma URL remota em runtime, SVGs sem referência externa, nenhuma primitiva criptográfica própria.
- Cria e lê arquivos KDBX com PyKeePass (formato compatível com KeePassXC), sem algoritmos de criptografia desenvolvidos neste projeto.
- **Segue automaticamente o tema ativo do Omarchy**, incluindo paletas claras ou escuras, botões, bordas, texto, seleções e ícones SVG colorizados. Atualiza em até aproximadamente 1,5 s após a troca de tema, sem reiniciar o aplicativo.
- Cadastro, edição, exclusão, pesquisa, categorias/pastas, favoritos, senhas geradas com `secrets` e backup do último estado.
- Proteção da senha mestra, ocultação de senha na interface, bloqueio automático após 5 min sem interação, ao minimizar **e ao suspender a sessão**; mensagens de erro genéricas (detalhes vão para `stderr`, sem vazar caminhos); permissões reapertadas para `0700`/`0600` a cada abertura/save; área de transferência com expiração de 20 s cobrindo `Clipboard` e `Selection`.
- Tenta marcar o clipboard como secreto com `x-kde-passwordManagerHint` e limpá-lo após 20 segundos, caso continue com o mesmo conteúdo.

## Integração automática de temas

A partir da versão **0.2.0** a aparência do keypassXD é controlada pelas cores do próprio Omarchy, não por uma seleção manual de temas. A aplicação lê, nessa ordem:

1. `~/.local/state/omarchy/current/theme/colors.toml` (Omarchy Quattro, tema atual).
2. `~/.config/omarchy/current/theme/colors.toml` (caminho de compatibilidade com instalações mais antigas).

São respeitadas as variáveis `XDG_STATE_HOME` e `XDG_CONFIG_HOME`, se definidas. As cores principais são `background`, `foreground`, `accent`, `selection`, `red` e `green` (com fallback para `color0`, `color7`, `color4`, `color1` e `color2` quando disponíveis). Os tons para superfície, menus, cartões, foco e hover são **derivados dessas cores**, sem uma paleta roxa fixa. A cor do texto dos botões de destaque é escolhida por contraste, e o texto principal de baixo contraste recebe um ajuste de legibilidade. A faixa lateral mostra o nome do tema ativo quando `theme.name` está disponível.

A cada **1,5 segundo**, a interface verifica o arquivo ativo. Isso também detecta quando o Omarchy aplica uma mudança trocando a pasta `theme` inteira. Todos os campos, janelas, caixas de diálogo e ícones SVG abertos são recoloridos. O plugin da barra usa as cores providas pelo shell do Omarchy (`WidgetButton`).

O conteúdo `colors.toml` **não é executado**: é interpretado com `tomllib` somente como dados de cores hexadecimais. Caso o arquivo esteja ausente ou temporariamente inválido durante a mudança, é usada uma paleta reserva e a sincronização é retomada automaticamente. **Trocar o tema não altera o cofre `.kdbx`**, nem sua chave de criptografia. A imagem `preview.png` ilustra a aparência da versão anterior e não mostra necessariamente suas cores locais.

Para conferir o tema atual no terminal:

```bash
cat "${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/current/theme/colors.toml"
```

Se você já instalou uma versão anterior, execute `./install.sh` da versão 0.3.0 para atualizar o aplicativo (o cofre existente é preservado e migra para Argon2id no próximo save). O instalador não remove arquivos `.kdbx`.

## Pré-requisitos

- Omarchy com o **shell Quattro** e comando `omarchy plugin`.
- Arch Linux/Omarchy com `python3`, módulo `venv` e acesso ao PyPI **durante a instalação**.
- Ambiente gráfico Wayland/Hyprland.
- Os pacotes `PySide6` e `pykeepass`, instalados em venv isolada e não no Python de sistema.

## Instalação

Via link do GitHub (recomendado — `install` é alias de `plugin add`):

```bash
omarchy plugin install https://github.com/yks777/keypassXD.git --enable
~/.config/omarchy/plugins/dev.keypassxd/install.sh
omarchy bar move dev.keypassxd --section right
```

O segundo passo é obrigatório: ele cria a venv em `~/.local/share/keypassxd/.venv`
(ou sob `$XDG_DATA_HOME`) com `PySide6` + `pykeepass`. É o único momento que usa
rede (PyPI). Para atualizar depois: `omarchy plugin update dev.keypassxd`.

Instalação manual (desenvolvimento):

```bash
git clone https://github.com/yks777/keypassXD.git
cd keypassXD
chmod +x install.sh
./install.sh
omarchy plugin enable dev.keypassxd
omarchy bar move dev.keypassxd --section right
```

Para testar sem usar o botão da barra:

```bash
~/.config/omarchy/plugins/dev.keypassxd/launch.sh
```

Ou verifique a compatibilidade do plugin:

```bash
omarchy plugin validate ~/.config/omarchy/plugins/dev.keypassxd
qmllint -I "$OMARCHY_PATH/shell" ~/.config/omarchy/plugins/dev.keypassxd/BarWidget.qml
```

O `install.sh` instala o código no caminho do Omarchy e cria a venv em `~/.local/share/keypassxd/.venv` (ou sob `$XDG_DATA_HOME`). Não usa `sudo`. O script não publica nem envia senhas a servidores.

## Onde ficam os arquivos

O banco é salvo em `$XDG_DATA_HOME/keypassxd/vault.kdbx` ou, na ausência da variável, `~/.local/share/keypassxd/vault.kdbx`. As permissões esperadas são diretório `0700` e cofre `0600`.

A versão anterior, também criptografada, fica em `vault.backup.kdbx`. Este backup guarda **apenas a versão imediatamente anterior**. Faça cópias criptografadas em outras unidades, de preferência com controle de versões.

É possível abrir esse `.kdbx` no KeePassXC. Para trabalhar com um cofre KeePassXC preexistente, **faça uma cópia de segurança primeiro**, feche ambos os aplicativos e copie seu arquivo `.kdbx` para `vault.kdbx` no diretório acima. Ainda não há seletor de arquivos ou importação de cofre pela interface.

## Segurança e limitações

1. KDBX é criptografado pela biblioteca PyKeePass (AES-256/ChaCha20, KDF Argon2id após a migração); a força efetiva depende também da senha mestra (mínimo 10 caracteres) e do custo KDF do banco criado. O projeto não implementa nenhum algoritmo criptográfico novo.
2. Não há sincronização em nuvem, extensão de navegador, TOTP, autofill, anexos, importação CSV, suporte a chave de hardware, proteção contra keyloggers ou wipe criptográfico de RAM. O script usa venv para isolar dependências Python.
3. **Importante no Omarchy:** gerenciadores de histórico da área de transferência podem salvar senhas. O MIME `x-kde-passwordManagerHint` depende do suporte do gerenciador; o timer não pode garantir remoção de cópias do histórico, apps que leram o clipboard ou serviços de sincronização. Revise cliphist/clipboard e desabilite histórico para credenciais confidenciais se necessário.
4. A memória de Python e Qt não é apagada de forma verificável ao bloquear a interface. Outros processos com acesso à mesma sessão do usuário, malware e processos com privilégios elevados continuam sendo riscos.
5. Alterações feitas simultaneamente no mesmo `.kdbx` pelo KeePassXC e keypassXD podem sobrescrever uma das versões. **Não abra a mesma base para edição simultânea**.
6. Se perder a senha mestra, não há recuperação automática. Guardar somente um backup no mesmo disco não protege contra falha física ou ransomware.
7. O ambiente de desenvolvimento desta entrega não possui Omarchy, PySide6 ou PyKeePass instalados, então o app **não foi validado em execução no Omarchy**; foram feitos testes estáticos, de geração e de estrutura. Use esta versão como protótipo a testar.

## Desinstalação

```bash
omarchy plugin disable dev.keypassxd
./uninstall.sh
```

O código do plugin é removido, mas **cofres e backups são preservados**. Não há exclusão automática de dados sensíveis.

## Desenvolvimento

- `manifest.json`: declara plugin `bar-widget` (cadeado na seção direita).
- `BarWidget.qml`: `BarIconButton` com glifo de cadeado do Nerd Font; só abre `launch.sh` (com `$HOME` expandido em aspas duplas via `bash -lc`).
- `app/main.py`: interface em Qt Widgets/PySide6 com atualização de tema durante a execução.
- `app/theme.py`: leitura das paletas do Omarchy, suporte a temas claros/escuros e cores derivadas.
- `app/styles.py`: CSS/QSS de Qt gerado a partir do tema em uso.
- `app/vault.py`: acesso KDBX e escrita transacional via arquivo temporário.
- `app/generator.py`: senhas aleatórias com `secrets`.
- `assets/icons/`: SVGs incluídos no projeto, não emojis, sem consultas à rede.

### Testes locais

```bash
python -m unittest discover -s tests -v
python -m compileall -q app
bash -n install.sh launch.sh uninstall.sh
```

Veja o [guia de desenvolvimento do Omarchy](https://plugins.omarchy.org/develop.html) e a [API de PyKeePass](https://github.com/libkeepass/pykeepass) para estender o projeto.

## Licença

MIT. O nome keypassXD não implica afiliação ao projeto KeePassXC.
