# CutShortPlus — Estúdio local de Shorts

Aplicativo Windows para pesquisar vídeos, identificar trechos, gerar Shorts/Reels verticais e gerenciar publicações. A interface HTML/JavaScript funciona com um servidor Python local em 127.0.0.1:8765.

## Requisitos

- Windows 10/11 e Python 3.10 ou superior disponível no terminal.
- Internet para instalar dependências, pesquisar vídeos e usar integrações opcionais.
- Node.js é opcional, usado apenas por alguns testes.
- FFmpeg é fornecido pela dependência Python imageio-ffmpeg.

## Instalação

1. Baixe ou clone o código-fonte em uma pasta local.
2. Execute **Start-CSP.exe** (ícone do aplicativo), ou use **Iniciar-CutShortPlus.cmd** como alternativa.
3. Na primeira execução, o inicializador cria um ambiente .venv e instala requirements.txt.
4. Abra http://127.0.0.1:8765 no navegador.

Nenhuma conta, chave ou credencial está pré-configurada. Caso não queira configurar IA, utilize a opção Sem IA na geração de Shorts.

## Ícone e inicializador Windows

O arquivo **Start-CSP.exe** é um inicializador gráfico do CutShortPlus, com ícone incorporado. Ele chama o script local `Iniciar-CutShortPlus.ps1`, aguarda a inicialização do servidor e abre o navegador. O executável não contém o servidor Python nem substitui as dependências de `requirements.txt`.

A marca visual é compartilhada entre `Start-CSP.exe`, a favicon e a barra lateral (`assets/cutshortplus.ico` e `assets/cutshortplus.png`). Para recompilar o inicializador no Windows com .NET Framework, execute `tools/Build-Start-CSP.ps1` no PowerShell. A versão distribuída não possui assinatura digital de editor.

## Recursos

- Pesquisa no YouTube, com filtros e títulos localizados quando a plataforma disponibiliza.
- Shorts manuais (1 a 10) ou Turbo Short, com limite de segurança de até 60 cortes por geração.
- Detecção de falas, avaliação de movimento e reenquadramento vertical automático.
- Exportação MP4 vertical em H.264/AAC, 720 x 1280.
- Estúdio ao vivo com busca, recomendações, gravação e exportação de trechos, quando o fluxo está disponível.
- Biblioteca de cortes, lixeira, restauração e exclusão com confirmação.
- Temas claro/escuro; seleção de modelos de IA com favoritos.
- Provedores opcionais: OpenAI, Anthropic (Claude), xAI (Grok), Google Gemini, DeepSeek, Mistral, Groq Cloud, OpenRouter e NVIDIA.

## Plugin Sendoka (SMS e OTP)

Em **Integrações → Sendoka**, configure uma chave `sok_test_...` (sandbox) ou `sok_live_...` (produção) e um remetente aprovado na sua conta Sendoka.
Salve a configuração. A chave é protegida por DPAPI no arquivo local `data/settings.json`, não é devolvida ao navegador e nunca deve ser incluída no Git.
Use destinatários no padrão internacional E.164 (ex.: `+5511999999999`). Para o Brasil, valide na sua conta se o serviço suporta a rota/destino e o remetente desejado.

- **Enviar SMS**: exige confirmação explícita, não realiza envio automático ou em massa e pode consumir segmentos/cota no modo produção.
- **Solicitar código OTP**: cria uma verificação de 6 dígitos válida por 10 minutos; a validação ocorre na API Sendoka. Em sandbox, o código documentado é `000000` (sem entrega real).
- **Ambiente**: a interface identifica se a chave é de teste ou produção. Não configure uma chave real sem planejar uso e custos.
- **Segurança**: HTTP somente para API Sendoka em HTTPS; credencial não entra nos logs nem nas respostas da API local. A origem das requisições locais continua limitada a `127.0.0.1:8765`.
- **Testes offline**: `python tools/test_sendoka_plugin.py` e `python tools/validate_sendoka_ui.py`; não enviam mensagens. A chave da conta e a autorização do remetente são necessárias para testar envios reais.
- **Documentação oficial**: https://www.sendoka.com/docs/guides/api/sms e https://www.sendoka.com/docs/guides/api/verify

O plugin é opcional e não altera a criação, edição ou publicação de vídeos.

## Segurança e dados locais

O repositório não contém dados de contas, vídeos pessoais, credenciais de API, históricos, bancos de dados nem caches.

Cada instalação gerencia seus próprios dados nas pastas locais data, cortes e imports. O aplicativo cria essas pastas automaticamente. O ambiente .venv e os caches também são gerados localmente. Esses caminhos são ignorados pelo Git por meio do .gitignore.

Chaves configuradas na interface Integrações são armazenadas localmente com proteção DPAPI no Windows. Não publique settings.json, arquivos de OAuth, tokens, backups, gravações, bancos SQLite, modelos baixados ou qualquer mídia de usuário.

Use Git para publicar apenas o código e arquivos de instalação. Revise a lista de arquivos antes do primeiro commit; o .gitignore não retira segredos de commits que já existam.

Alguns provedores cobram por inferência e exigem saldo ou permissões. Listar modelos não comprova que uma chave pode gerar conteúdo.

## Diagnóstico e distribuição

A distribuição pública contém somente os arquivos necessários para executar o aplicativo.
Scripts de testes e fixtures internas de desenvolvimento foram mantidos no arquivo privado,
fora da pasta publicável. Para iniciar uma instalação limpa, execute Iniciar-CutShortPlus.cmd.

## Direitos e limitações

Utilize apenas vídeos e transmissões cujos direitos e termos de uso permitam edição, gravação e publicação. Revise os resultados antes de publicar. O mapa de trechos mais reproduzidos do YouTube pode não estar disponível para todos os vídeos.

**Licença:** CutShortPlus Source-Available 1.0, licença personalizada de código-fonte disponível. Leia o arquivo [LICENSE](LICENSE) antes de usar ou redistribuir.

Copyright (c) 2026 Erick I Gaudêncio B. Todos os direitos reservados.

É permitido consultar o código, executar o aplicativo gratuitamente (inclusive para uso interno em empresas), realizar modificações privadas e compartilhar gratuitamente **somente a versão original inalterada**, mantendo os créditos e a licença. É proibido vender ou oferecer o próprio CutShortPlus como produto ou serviço, publicar versões modificadas sem autorização escrita ou utilizar sua marca e identidade visual de forma independente sem autorização. Conteúdos produzidos legitimamente com o aplicativo não são automaticamente abrangidos por essa proibição de comercialização do software.

**Não é uma licença open source aprovada pela OSI.** Dependências de terceiros mantêm suas próprias licenças. Para redistribuição ou exceções comerciais, consulte integralmente o arquivo LICENSE.
