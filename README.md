# CutShortPlus — Estúdio local de Shorts

Aplicativo Windows para pesquisar vídeos, identificar trechos, gerar Shorts/Reels verticais e gerenciar publicações. A interface HTML/JavaScript funciona com um servidor Python local em 127.0.0.1:8765.

## Requisitos

- Windows 10/11 e Python 3.10 ou superior disponível no terminal.
- Internet para instalar dependências, pesquisar vídeos e usar integrações opcionais.
- Node.js é opcional, usado apenas por alguns testes.
- FFmpeg é fornecido pela dependência Python imageio-ffmpeg.

## Instalação

1. Baixe ou clone o código-fonte em uma pasta local.
2. Execute Iniciar-CutShortPlus.cmd.
3. Na primeira execução, o inicializador cria um ambiente .venv e instala requirements.txt.
4. Abra http://127.0.0.1:8765 no navegador.

Nenhuma conta, chave ou credencial está pré-configurada. Caso não queira configurar IA, utilize a opção Sem IA na geração de Shorts.

## Recursos

- Pesquisa no YouTube, com filtros e títulos localizados quando a plataforma disponibiliza.
- Shorts manuais (1 a 10) ou Turbo Short, com limite de segurança de até 60 cortes por geração.
- Detecção de falas, avaliação de movimento e reenquadramento vertical automático.
- Exportação MP4 vertical em H.264/AAC, 720 x 1280.
- Estúdio ao vivo com busca, recomendações, gravação e exportação de trechos, quando o fluxo está disponível.
- Biblioteca de cortes, lixeira, restauração e exclusão com confirmação.
- Temas claro/escuro; seleção de modelos de IA com favoritos.
- Provedores opcionais: OpenAI, Anthropic (Claude), xAI (Grok), Google Gemini, DeepSeek, Mistral, Groq Cloud, OpenRouter e NVIDIA.

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
