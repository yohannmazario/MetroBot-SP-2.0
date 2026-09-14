# MetrôBot SP 2.0

Assistente de rotas do metrô de São Paulo — linhas **1-Azul**, **2-Verde** e **3-Vermelha**.

Projeto de **Yohann Mazario**.

Roda **só na máquina**, com o arquivo `metrobot_app.py`. Você pede o caminho em português (*“Estou na Sé e quero ir ao MASP”*). A IA **entende** o pedido e **explica** a viagem. Quem **escolhe** a rota é o algoritmo (BFS ou DFS).

> *A IA conversa. O algoritmo decide. O mapa mostra só o trecho da viagem.*

## Como rodar

1. Instale Python 3.10+ e, nesta pasta:
   ```bat
   python -m pip install -r requirements.txt
   ```
2. Copie `.env.example` para `.env` e cole sua chave:
   ```
   GROQ_API_KEY=gsk_sua_chave_aqui
   ```
   Sem chave, o app roda em **modo offline** (busca e mapa continuam).
3. Dê dois cliques em `iniciar_MetroBot.bat` **ou** rode:
   ```bat
   python metrobot_app.py
   ```

## No app

- Escreva no campo do meio, por exemplo: *Estou na Sé e quero ir ao MASP*
- Ou escolha **Origem** e **Destino** e clique em **Traçar rota**
- O **mapa só aparece depois** da busca e mostra **somente o trecho** da viagem
- Troque **Claro / Escuro** no topo

Para gerar o `.exe`: `gerar_exe.bat`.

## O que o `metrobot_app.py` faz

- 52 estações das três linhas, sem duplicar as de integração
- BFS e DFS com estações fechadas
- Regras de integração e horário de pico
- Chat com Llama (Groq) e modo offline
- Mapa esquemático da rota

A chave da API **não** vai no código nem no Git. Use o arquivo `.env` local.
