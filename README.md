# Option Strategy Bot for Bybit

Este projeto é um robô em Python para a análise e geração de sinais de estratégias com opções, utilizando dados da Bybit (via ccxt) e o modelo Black–Scholes para precificação realista. Os sinais são armazenados e monitorados em um banco de dados SQLite, com informações detalhadas para cada perna da operação.

## Índice

- [Visão Geral](#visão-geral)
- [Funcionalidades](#funcionalidades)
- [Requisitos](#requisitos)
- [Instalação e Configuração](#instalação-e-configuração)
- [Uso](#uso)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Documentação do Código](#documentação-do-código)
  - [Modelo Black–Scholes](#modelo-black–scholes)
  - [Classe `OptionStrategyBot`](#classe-optionstrategybot)
  - [Classe `SignalDatabase`](#classe-signaldatabase)
- [Contribuição](#contribuição)
- [Licença](#licença)
- [Contato](#contato)

## Visão Geral

O **Option Strategy Bot for Bybit** é um sistema automatizado que:

- Obtém preços do ativo subjacente e simula a obtenção de dados de opções para pares USDT.
- Utiliza o modelo Black–Scholes para calcular preços teóricos das opções (calls e puts) com base em parâmetros reais, como:
  - Preço do ativo (S)
  - Strike (K)
  - Tempo até a expiração (T)
  - Taxa livre de risco (r)
  - Volatilidade (IV, utilizada como sigma)
- Gera sinais para três estratégias principais:
  - **Short Strangle:** Venda simultânea de uma call OTM e uma put OTM.
  - **Bull Call Spread:** Venda de uma call OTM e compra de uma call com strike maior para proteção.
  - **Bear Put Spread:** Venda de uma put OTM e compra de uma put com strike menor para proteção.
- Ajusta dinamicamente as quantidades operadas (valor padrão de 0.01 por perna) conforme os prêmios calculados.
- Armazena os sinais gerados no banco de dados SQLite e grava, em uma tabela relacionada, os valores reais dos prêmios de cada perna e as quantidades.
- Monitora os sinais ativos e emite notificações quando um sinal se aproxima da expiração ou quando o tempo decorrido indica que o lucro máximo foi atingido, sugerindo a rolagem da posição.

## Funcionalidades

- **Precificação Realista:** Utiliza o modelo Black–Scholes para calcular os preços teóricos das opções.
- **Geração de Sinais:** Cria sinais para múltiplas estratégias (Short Strangle, Bull Call Spread e Bear Put Spread) com detalhes completos, incluindo os prêmios individuais de cada perna.
- **Ajuste Dinâmico de Quantidades:** Se um dos prêmios for significativamente maior que o outro (diferença de 10% ou mais), o valor operado dessa perna é ajustado (aumentado em 50%).
- **Armazenamento e Monitoramento:** Utiliza SQLite para armazenar os sinais e os detalhes de cada perna em tabelas relacionadas, evitando duplicidades.
- **Notificação de Rolagem:** Monitora os sinais e notifica quando é o momento de rolar a posição com base na proximidade da expiração ou no tempo decorrido indicando lucro máximo.

## Requisitos

- **Python 3.6+**
- Módulos Python:
  - `ccxt` (para interação com a API da Bybit)
  - `sqlite3` (módulo nativo para SQLite)
  - Outras bibliotecas padrão: `time`, `json`, `datetime`, `math`
- Se desejar utilizar endpoints privados da Bybit, você precisará de credenciais (API_KEY e API_SECRET).

## Instalação e Configuração

1. **Clone o repositório:**

   ```bash
   git clone https://github.com/seu_usuario/option-strategy-bot.git
   cd option-strategy-bot
   ```

2. **Crie e ative um ambiente virtual (opcional, mas recomendado):**

   ```bash
   python -m venv venv
   source venv/bin/activate   # No Windows: venv\Scripts\activate
   ```

3. **Instale as dependências:**

   ```bash
   pip install ccxt
   ```

4. **Configure as credenciais (opcional):**

   No arquivo principal, defina as variáveis `API_KEY` e `API_SECRET` se desejar utilizar endpoints privados. Caso contrário, deixe-as como `None` para utilizar apenas dados públicos.

## Uso

O projeto é executado continuamente em um loop que:

- Realiza a análise dos ativos definidos (por padrão, BTC, ETH e SOL).
- Gera sinais com base nas condições de mercado e no modelo Black–Scholes.
- Insere os sinais e os detalhes de cada perna no banco de dados SQLite.
- Monitora os sinais e emite notificações quando um sinal deve ser rolado.

Para executar o projeto:

```bash
python seu_arquivo_principal.py
```

> **Dica:** Utilize o Git Bash ou outro terminal de sua preferência para executar o comando.

## Estrutura do Projeto

A estrutura principal dos arquivos é a seguinte:

```
option-strategy-bot/
├── README.md               # Documentação completa do projeto
├── signals.db              # Banco de dados SQLite (gerado automaticamente)
├── seu_arquivo_principal.py  # Código principal do projeto (contendo as classes e a execução do loop)
└── requirements.txt        # (Opcional) Lista de dependências do projeto
```

## Documentação do Código

### Modelo Black–Scholes

- **`norm_cdf(x)`**  
  Calcula a função de distribuição cumulativa da distribuição normal padrão usando a função de erro (`erf`).

- **`black_scholes_price(S, K, T, r, sigma, option_type)`**  
  Calcula o preço teórico de uma opção (call ou put) com base no preço do ativo `S`, strike `K`, tempo até expiração `T` (em anos), taxa livre de risco `r` e volatilidade `sigma` (IV).  
  Se `T` for zero ou negativo, retorna o valor intrínseco da opção.

### Classe `OptionStrategyBot`

Responsável por:
- Obter o preço do ativo e simular a obtenção de dados de opções para pares USDT.
- Calcular o tempo até a expiração em anos.
- Utilizar o modelo Black–Scholes para precificar cada perna das opções.
- Gerar sinais para as seguintes estratégias:
  - **Short Strangle:** Calcula os prêmios teóricos de uma call e de uma put OTM. Ajusta as quantidades se um dos prêmios for 10% maior que o outro.
  - **Bull Call Spread:** Calcula o crédito líquido (diferença entre o prêmio recebido da call vendida e o custo da call comprada). Pode resultar em débito (valor negativo) ou crédito.
  - **Bear Put Spread:** Calcula o crédito líquido para a operação com puts, similar ao Bull Call Spread.
- Cada sinal gerado inclui os detalhes do prêmio total, os prêmios individuais de cada perna (armazenados em `leg_premiums`), e instruções de rolagem.

### Classe `SignalDatabase`

Responsável por:
- Criar e gerenciar o banco de dados SQLite.
- Armazenar os sinais gerados na tabela `signals` e os detalhes de cada perna na tabela relacionada `signal_legs`.
- Verificar duplicidade de sinais antes da inserção.
- Monitorar sinais ativos e emitir notificações de rolagem quando os critérios (proximidade da expiração ou lucro máximo simulado) forem atendidos.

## Contribuição

Contribuições são bem-vindas! Para contribuir:

1. Faça um fork do repositório.
2. Crie uma branch para sua feature: `git checkout -b minha-feature`.
3. Faça os commits e envie sua branch: `git push origin minha-feature`.
4. Abra um Pull Request no repositório principal.

## Licença

Este projeto é licenciado sob a [MIT License](LICENSE).

## Contato

Se tiver dúvidas, sugestões ou contribuições, sinta-se à vontade para abrir uma _issue_ no GitHub ou entrar em contato pelo seu método preferido.
