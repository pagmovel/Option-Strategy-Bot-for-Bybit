import ccxt
import time
import sqlite3
import json
import pytz
from datetime import datetime, timedelta
from math import log, sqrt, exp, erf


def norm_cdf(x):
    """
    Calcula a função de distribuição cumulativa (CDF) da distribuição normal padrão,
    utilizando a função de erro (erf).

    :param x: Valor para o qual se calcula a CDF.
    :return: CDF do valor x.
    """
    return (1.0 + erf(x / sqrt(2.0))) / 2.0


def black_scholes_price(S, K, T, r, sigma, option_type):
    """
    Calcula o preço de uma opção utilizando o modelo Black–Scholes.

    :param S: Preço atual do ativo subjacente.
    :param K: Strike da opção.
    :param T: Tempo até a expiração, em anos.
    :param r: Taxa livre de risco anual (decimal).
    :param sigma: Volatilidade do ativo (IV) em decimal.
    :param option_type: Tipo de opção ('call' ou 'put').
    :return: Preço da opção.
    """
    if T <= 0:
        # Se a opção já expirou, retorna o valor intrínseco.
        if option_type == "call":
            return max(S - K, 0)
        elif option_type == "put":
            return max(K - S, 0)
        else:
            return None
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if option_type == "call":
        return S * norm_cdf(d1) - K * exp(-r * T) * norm_cdf(d2)
    elif option_type == "put":
        return K * exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    else:
        return None
    


class SignalDatabase:
    """
    Classe para gerenciamento do banco de dados SQLite que armazena os sinais gerados.

    Tabelas:
      - signals: armazena os sinais gerais (ativo, estratégia, expiração, prêmio total, detalhes do sinal,
                 instrução de rolagem, timestamp e status).
      - signal_legs: armazena os valores reais dos prêmios e as quantidades de cada perna associadas a um sinal.
    """

    def __init__(self, db_name="signals.db"):
        """
        Inicializa a conexão com o banco de dados e cria as tabelas necessárias.

        :param db_name: Nome do arquivo SQLite.
        """
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_signals_table()
        self.create_leg_table()

    def create_signals_table(self):
        """
        Cria a tabela 'signals' se ela ainda não existir.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT,
                strategy TEXT,
                expiration TEXT,
                premium REAL,
                signal_details TEXT,
                roll_instruction TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        """
        )
        self.conn.commit()

    def create_leg_table(self):
        """
        Cria a tabela 'signal_legs' se ela ainda não existir.
        Essa tabela armazena os valores reais dos prêmios e as quantidades operadas para cada perna.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                leg TEXT,
                premium REAL,
                quantity REAL,
                FOREIGN KEY (signal_id) REFERENCES signals(id)
            )
        """
        )
        self.conn.commit()

    def signal_exists(self, asset, strategy, expiration):
        """
        Verifica se já existe um sinal ativo para o mesmo ativo, estratégia e expiração.

        :param asset: Ativo (ex: 'BTC').
        :param strategy: Estratégia (ex: 'Short Strangle').
        :param expiration: Data de expiração (ex: 'YYYY-MM-DD').
        :return: True se o sinal já existir, False caso contrário.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id FROM signals WHERE asset=? AND strategy=? AND expiration=? AND status='active'",
            (asset, strategy, expiration),
        )
        row = cursor.fetchone()
        return row is not None

    def insert_signal(self, asset, strategy, expiration, premium, signal_details, roll_instruction):
        """
        Insere um novo sinal na tabela 'signals', se não for duplicado.
        Retorna o ID do sinal inserido ou None se já existir.

        :param asset: Ativo (ex: 'BTC').
        :param strategy: Estratégia (ex: 'Short Strangle').
        :param expiration: Data de expiração (ex: 'YYYY-MM-DD').
        :param premium: Prêmio total da operação.
        :param signal_details: Detalhes do sinal (dicionário convertido para JSON), incluindo 'leg_premiums'.
        :param roll_instruction: Instrução de rolagem.
        :return: ID do sinal inserido ou None.
        """
        if self.signal_exists(asset, strategy, expiration):
            return None
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO signals (asset, strategy, expiration, premium, signal_details, roll_instruction)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (asset, strategy, expiration, premium, json.dumps(signal_details), roll_instruction),
        )
        self.conn.commit()
        return cursor.lastrowid

    def insert_signal_leg(self, signal_id, leg, premium, quantity):
        """
        Insere os detalhes de uma perna da operação na tabela 'signal_legs'.

        :param signal_id: ID do sinal associado.
        :param leg: Nome da perna (ex: 'sell_call', 'sold_call', etc.).
        :param premium: Valor do prêmio dessa perna.
        :param quantity: Quantidade operada nessa perna.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO signal_legs (signal_id, leg, premium, quantity)
            VALUES (?, ?, ?, ?)
        """,
            (signal_id, leg, premium, quantity),
        )
        self.conn.commit()

    def insert_signal_legs(self, signal_id, signal, default_qty):
        """
        Se o sinal contiver a chave 'leg_premiums', insere os valores reais dos prêmios e quantidades
        de cada perna na tabela 'signal_legs'.

        :param signal_id: ID do sinal inserido.
        :param signal: Dicionário com os detalhes do sinal.
        :param default_qty: Quantidade padrão a ser utilizada se não definida.
        """
        if "leg_premiums" in signal:
            for leg_key, premium_value in signal["leg_premiums"].items():
                leg_details = signal.get(leg_key, {})
                quantity = leg_details.get("quantity", default_qty)
                self.insert_signal_leg(signal_id, leg_key, premium_value, quantity)

    def check_roll_signals(self, roll_threshold_days=2, profit_threshold=0.75):
        tz = pytz.timezone("America/Recife")
        now = datetime.now(tz)
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, asset, strategy, expiration, premium, roll_instruction, timestamp FROM signals WHERE status = 'active'"
        )
        rows = cursor.fetchall()
        notifications = []
        for row in rows:
            (signal_id, asset, strategy, expiration, premium, roll_instruction, entry_timestamp) = row
            try:
                exp_date_naive = datetime.strptime(expiration, "%Y-%m-%d")
                exp_date = tz.localize(exp_date_naive)
                entry_date_naive = datetime.strptime(entry_timestamp, "%Y-%m-%d %H:%M:%S")
                entry_date = tz.localize(entry_date_naive)
            except Exception as e:
                continue

            time_to_exp = exp_date - now
            notify_exp = time_to_exp <= timedelta(days=roll_threshold_days)
            total_time = exp_date - entry_date
            elapsed = now - entry_date
            profit_fraction = (elapsed.total_seconds() / total_time.total_seconds() if total_time.total_seconds() > 0 else 0)
            notify_profit = profit_fraction >= profit_threshold

            if notify_exp or notify_profit:
                if notify_exp and notify_profit:
                    message = (
                        f"Signal ID {signal_id} ({asset} - {strategy}) está próximo da expiração ({expiration}) "
                        f"e atingiu {profit_fraction*100:.1f}% do tempo decorrido. "
                        f"Instrução de Rolagem: {roll_instruction}"
                    )
                elif notify_exp:
                    message = (
                        f"Signal ID {signal_id} ({asset} - {strategy}) está próximo da expiração ({expiration}). "
                        f"Instrução de Rolagem: {roll_instruction}"
                    )
                else:
                    message = (
                        f"Signal ID {signal_id} ({asset} - {strategy}) atingiu {profit_fraction*100:.1f}% do tempo decorrido "
                        f"(indicativo de lucro máximo). Instrução de Rolagem: {roll_instruction}"
                    )
                notifications.append(message)
                cursor.execute("UPDATE signals SET status = 'rolled' WHERE id = ?", (signal_id,))
        self.conn.commit()
        return notifications


class OptionStrategyBot:
    """
    Classe para análise e geração de sinais de estratégias de opções utilizando dados da Bybit.

    Estratégias implementadas:
      - Short Strangle: Vende uma call OTM e uma put OTM simultaneamente.
      - Bull Call Spread: Vende uma call OTM e compra outra call com strike maior para proteção.
      - Bear Put Spread: Vende uma put OTM e compra outra put com strike menor para proteção.

    Cada sinal inclui:
      - Preço calculado utilizando Black–Scholes (com base em S, K, T, r e IV).
      - Quantidade padrão de operação, definida conforme o ativo.
      - Armazenamento dos prêmios de cada perna em 'leg_premiums'.
      - Instruções de rolagem para a próxima expiração.
    """

    def __init__(self, api_key=None, secret=None, quote_currency="USDT", r=0.01):
        """
        Inicializa o robô.

        :param api_key: Chave da API (opcional).
        :param secret: Chave secreta da API (opcional).
        :param quote_currency: Moeda de cotação (padrão: "USDT").
        :param r: Taxa livre de risco anual (padrão: 0.01 ou 1%).
        """
        self.quote_currency = quote_currency
        self.r = r
        if api_key and secret:
            self.exchange = ccxt.bybit({"apiKey": api_key, "secret": secret})
        else:
            self.exchange = ccxt.bybit()  # Usa apenas endpoints públicos
        self.assets = ["BTC", "ETH", "SOL"]
        self.iv_threshold = 0.50
        self.asset_min_qty = {"BTC": 0.01, "ETH": 0.01, "SOL": 0.1}

    def fetch_underlying_price(self, asset):
        """
        Obtém o preço do ativo subjacente para o par asset/quote_currency.

        :param asset: Nome do ativo (ex: 'BTC').
        :return: Preço atual do ativo ou None se ocorrer erro.
        """
        symbol = f"{asset}/{self.quote_currency}"
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker["last"]
        except Exception as e:
            print(f"Erro ao buscar ticker para {symbol}: {e}")
            return None

    def fetch_options_data(self, asset):
        """
        Simula a obtenção de dados de opções para o ativo.
        (Essa função deve ser ajustada para usar dados reais, se disponíveis.)

        Gera automaticamente vencimentos semanais até 180 dias a partir de hoje.

        :param asset: Nome do ativo (ex: 'BTC').
        :return: Dicionário contendo:
                  - 'expirations': lista de datas de vencimento no formato 'YYYY-MM-DD'.
                  - 'calls': lista de calls com strike, IV e símbolo.
                  - 'puts': lista de puts com strike, IV e símbolo.
        """
        underlying_price = self.fetch_underlying_price(asset)
        if underlying_price is None:
            underlying_price = 0
        tz = pytz.timezone("America/Recife")
        now = datetime.now(tz)
        expirations = []
        start = now + timedelta(days=7)
        end = now + timedelta(days=180)
        current = start
        while current <= end:
            expirations.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=7)
        return {
            "expirations": expirations,
            "calls": [
                {
                    "strike": 1.10 * underlying_price,
                    "iv": 0.60,
                    "symbol": f"{asset}_CALL_OTM1",
                },
                {
                    "strike": 1.15 * underlying_price,
                    "iv": 0.55,
                    "symbol": f"{asset}_CALL_OTM2",
                },
            ],
            "puts": [
                {
                    "strike": 0.90 * underlying_price,
                    "iv": 0.65,
                    "symbol": f"{asset}_PUT_OTM1",
                },
                {
                    "strike": 0.85 * underlying_price,
                    "iv": 0.70,
                    "symbol": f"{asset}_PUT_OTM2",
                },
            ],
        }

    def time_to_expiration(self, expiration):
        """
        Calcula o tempo até a expiração em anos.

        :param expiration: Data de expiração no formato 'YYYY-MM-DD'.
        :return: Tempo até expiração (T) em anos.
        """
        try:
            tz = pytz.timezone("America/Recife")
            exp_date_naive = datetime.strptime(expiration, "%Y-%m-%d")
            exp_date = tz.localize(exp_date_naive)
            now = datetime.now(tz)
            T_seconds = (exp_date - now).total_seconds()
            T_years = T_seconds / (365 * 24 * 3600)
            return max(T_years, 0)  # Garante que T não seja negativo
        except Exception as e:
            print(f"Erro ao calcular T para expiração {expiration}: {e}")
            return 0

    def analyze_and_generate_short_strangle(self, asset):
        """
        Analisa o ativo para gerar sinais de Short Strangle para todos os vencimentos
        disponíveis até 6 meses.

        :param asset: Nome do ativo (ex: 'BTC').
        :return: Lista de tuplas (sinal, roll_instruction) para cada vencimento válido.
        """
        price = self.fetch_underlying_price(asset)
        if price is None:
            return []
        options_data = self.fetch_options_data(asset)
        tz = pytz.timezone("America/Recife")
        now = datetime.now(tz)
        valid_exps = [exp for exp in options_data.get("expirations", [])
                      if 0 <= (tz.localize(datetime.strptime(exp, "%Y-%m-%d")) - now).days <= 180]
        signals_list = []
        for expiration in valid_exps:
            T = self.time_to_expiration(expiration)
            otm_calls = [op for op in options_data["calls"] if op["strike"] > price]
            otm_puts = [op for op in options_data["puts"] if op["strike"] < price]
            default_qty = self.asset_min_qty.get(asset, 0.01)
            if otm_calls and otm_puts:
                call_to_sell = min(otm_calls, key=lambda x: x["strike"])
                put_to_sell = max(otm_puts, key=lambda x: x["strike"])
                premium_call = black_scholes_price(price, call_to_sell["strike"], T, self.r, call_to_sell["iv"], "call")
                premium_put = black_scholes_price(price, put_to_sell["strike"], T, self.r, put_to_sell["iv"], "put")
                total_premium = premium_call + premium_put
                leg_premiums = {"sell_call": premium_call, "sell_put": premium_put}
                sell_call_qty = default_qty
                sell_put_qty = default_qty
                if premium_call > premium_put * 1.1:
                    sell_call_qty = default_qty * 1.5
                elif premium_put > premium_call * 1.1:
                    sell_put_qty = default_qty * 1.5
                if (call_to_sell["iv"] + put_to_sell["iv"]) / 2.0 > self.iv_threshold:
                    roll_instruction = "Fechar posições e montar novo Short Strangle para a próxima expiração."
                    call_to_sell.update({"quantity": sell_call_qty})
                    put_to_sell.update({"quantity": sell_put_qty})
                    signal = {
                        "strategy": "Short Strangle",
                        "sell_call": call_to_sell,
                        "sell_put": put_to_sell,
                        "expiration": expiration,
                        "premium": total_premium,
                        "leg_premiums": leg_premiums,
                        "rationale": f"IV média acima do limiar. Preços: call={premium_call:.4f}, put={premium_put:.4f}.",
                    }
                else:
                    roll_instruction = ""
                    signal = {
                        "strategy": "No Trade - Short Strangle",
                        "expiration": expiration,
                        "premium": total_premium,
                        "leg_premiums": leg_premiums,
                        "rationale": f"IV média abaixo do limiar. Preços: call={premium_call:.4f}, put={premium_put:.4f}.",
                    }
            else:
                roll_instruction = ""
                signal = {
                    "strategy": "No Trade - Short Strangle",
                    "expiration": expiration,
                    "premium": 0,
                    "leg_premiums": {},
                    "rationale": "Opções OTM não disponíveis.",
                }
            signals_list.append((signal, roll_instruction))
        return signals_list

    def analyze_and_generate_bull_call_spread(self, asset):
        """
        Analisa o ativo para gerar sinais de Bull Call Spread para todos os vencimentos
        disponíveis até 6 meses.

        :param asset: Nome do ativo (ex: 'BTC').
        :return: Lista de tuplas (sinal, roll_instruction) para cada vencimento válido.
        """
        price = self.fetch_underlying_price(asset)
        if price is None:
            return []
        options_data = self.fetch_options_data(asset)
        tz = pytz.timezone("America/Recife")
        now = datetime.now(tz)
        valid_exps = [exp for exp in options_data.get("expirations", [])
                      if 0 <= (tz.localize(datetime.strptime(exp, "%Y-%m-%d")) - now).days <= 180]
        signals_list = []
        for expiration in valid_exps:
            T = self.time_to_expiration(expiration)
            calls = options_data["calls"]
            if len(calls) >= 2:
                sorted_calls = sorted(calls, key=lambda x: x["strike"])
                sold_call = next((op for op in sorted_calls if op["strike"] > price), None)
                if sold_call is None:
                    signal = {
                        "strategy": "No Trade - Bull Call Spread",
                        "rationale": "Nenhuma call OTM disponível.",
                        "expiration": expiration,
                        "premium": 0,
                    }
                    signals_list.append((signal, ""))
                    continue
                index = sorted_calls.index(sold_call)
                if index + 1 < len(sorted_calls):
                    bought_call = sorted_calls[index + 1]
                else:
                    signal = {
                        "strategy": "No Trade - Bull Call Spread",
                        "rationale": "Não há call para proteção.",
                        "expiration": expiration,
                        "premium": 0,
                    }
                    signals_list.append((signal, ""))
                    continue

                sold_call_premium = black_scholes_price(price, sold_call["strike"], T, self.r, sold_call["iv"], "call")
                bought_call_cost = black_scholes_price(price, bought_call["strike"], T, self.r, bought_call["iv"], "call")
                net_credit = sold_call_premium - bought_call_cost
                leg_premiums = {"sold_call": sold_call_premium, "bought_call": bought_call_cost}
                qty = self.asset_min_qty.get(asset, 0.01)
                if net_credit > price * 0.001:
                    qty = self.asset_min_qty.get(asset, 0.01) * 1.5
                sold_call.update({"quantity": qty})
                bought_call.update({"quantity": qty})
                roll_instruction = "Fechar a trava de alta e montar nova trava para a próxima expiração."
                signal = {
                    "strategy": "Bull Call Spread",
                    "sell_call": sold_call,
                    "buy_call": bought_call,
                    "expiration": expiration,
                    "premium": net_credit,
                    "leg_premiums": leg_premiums,
                    "rationale": f"Crédito líquido: {net_credit:.4f}.",
                }
            else:
                roll_instruction = ""
                signal = {
                    "strategy": "No Trade - Bull Call Spread",
                    "expiration": expiration,
                    "premium": 0,
                    "leg_premiums": {},
                    "rationale": "Dados insuficientes de opções.",
                }
            signals_list.append((signal, roll_instruction))
        return signals_list

    def analyze_and_generate_bear_put_spread(self, asset):
        """
        Analisa o ativo para gerar sinais de Bear Put Spread para todos os vencimentos
        disponíveis até 6 meses.

        :param asset: Nome do ativo (ex: 'BTC').
        :return: Lista de tuplas (sinal, roll_instruction) para cada vencimento válido.
        """
        price = self.fetch_underlying_price(asset)
        if price is None:
            return []
        options_data = self.fetch_options_data(asset)
        tz = pytz.timezone("America/Recife")
        now = datetime.now(tz)
        valid_exps = [exp for exp in options_data.get("expirations", [])
                      if 0 <= (tz.localize(datetime.strptime(exp, "%Y-%m-%d")) - now).days <= 180]
        signals_list = []
        for expiration in valid_exps:
            T = self.time_to_expiration(expiration)
            puts = options_data["puts"]
            if len(puts) >= 2:
                sorted_puts = sorted(puts, key=lambda x: x["strike"], reverse=True)
                sold_put = next((op for op in sorted_puts if op["strike"] < price), None)
                if sold_put is None:
                    signal = {
                        "strategy": "No Trade - Bear Put Spread",
                        "rationale": "Nenhuma put OTM disponível.",
                        "expiration": expiration,
                        "premium": 0,
                    }
                    signals_list.append((signal, ""))
                    continue
                index = sorted_puts.index(sold_put)
                if index + 1 < len(sorted_puts):
                    bought_put = sorted_puts[index + 1]
                else:
                    signal = {
                        "strategy": "No Trade - Bear Put Spread",
                        "rationale": "Não há put para proteção.",
                        "expiration": expiration,
                        "premium": 0,
                    }
                    signals_list.append((signal, ""))
                    continue

                sold_put_premium = black_scholes_price(price, sold_put["strike"], T, self.r, sold_put["iv"], "put")
                bought_put_cost = black_scholes_price(price, bought_put["strike"], T, self.r, bought_put["iv"], "put")
                net_credit = sold_put_premium - bought_put_cost
                leg_premiums = {"sold_put": sold_put_premium, "bought_put": bought_put_cost}
                qty = self.asset_min_qty.get(asset, 0.01)
                if net_credit > price * 0.001:
                    qty = self.asset_min_qty.get(asset, 0.01) * 1.5
                sold_put.update({"quantity": qty})
                bought_put.update({"quantity": qty})
                roll_instruction = "Fechar a trava de baixa e montar nova trava para a próxima expiração."
                signal = {
                    "strategy": "Bear Put Spread",
                    "sell_put": sold_put,
                    "buy_put": bought_put,
                    "expiration": expiration,
                    "premium": net_credit,
                    "leg_premiums": leg_premiums,
                    "rationale": f"Crédito líquido: {net_credit:.4f}.",
                }
            else:
                roll_instruction = ""
                signal = {
                    "strategy": "No Trade - Bear Put Spread",
                    "expiration": expiration,
                    "premium": 0,
                    "leg_premiums": {},
                    "rationale": "Dados insuficientes de opções.",
                }
            signals_list.append((signal, roll_instruction))
        return signals_list

    def run(self):
        """
        Executa a análise para cada ativo configurado e gera os sinais para cada estratégia.
        Para cada ativo, gera uma lista de sinais para cada estratégia (baseados em cada vencimento válido).

        :return: Dicionário com os sinais gerados, onde cada chave é um ativo e o valor é um dicionário
                 com cada estratégia contendo uma lista de tuplas (sinal, roll_instruction).
        """
        signals = {}
        for asset in self.assets:
            print(f"\n=== Análise do ativo: {asset}/{self.quote_currency} ===")
            short_strangle_signals = self.analyze_and_generate_short_strangle(asset)
            bull_call_signals = self.analyze_and_generate_bull_call_spread(asset)
            bear_put_signals = self.analyze_and_generate_bear_put_spread(asset)
            signals[asset] = {
                "short_strangle": short_strangle_signals,
                "bull_call_spread": bull_call_signals,
                "bear_put_spread": bear_put_signals,
            }
            time.sleep(1)  # Pequeno delay para evitar rate limits
        return signals


# Execução contínua do robô: gera sinais, insere no banco e verifica se é hora de rolar as posições
if __name__ == "__main__":
    # Defina API_KEY e API_SECRET se desejar utilizar endpoints privados; caso contrário, deixe como None
    API_KEY = None
    API_SECRET = None

    bot = OptionStrategyBot(API_KEY, API_SECRET, quote_currency="USDT", r=0.01)
    db = SignalDatabase("signals.db")

    while True:
        try:
            results = bot.run()
            print("\n=== Sinais de Entrada Gerados ===")
            for asset, strategies in results.items():
                # Para cada estratégia do ativo, iteramos sobre cada sinal gerado (para cada vencimento)
                for strat_name, signals_list in strategies.items():
                    for signal, roll_instruction in signals_list:
                        # Se o sinal for de "No Trade" ou "Erro", exibe os detalhes (não são gravados)
                        if ("No Trade" in signal["strategy"]) or ("Erro" in signal["strategy"]):
                            print(f"\nEstratégia: {strat_name}")
                            for key, value in signal.items():
                                print(f"{key}: {value}")
                        else:
                            # Para sinais válidos, tenta inseri-los no banco
                            signal_id = db.insert_signal(
                                asset,
                                signal["strategy"],
                                signal.get("expiration", ""),
                                signal.get("premium", 0),
                                signal,
                                roll_instruction,
                            )
                            if signal_id is None:
                                # Se já existir, exibe somente a mensagem reduzida
                                print(f"\nSinal para {asset} - {signal['strategy']} com expiração {signal.get('expiration', '')} já existe.")
                            else:
                                # Se inserido, exibe os logs detalhados
                                print("-" * 80)
                                print(f"\nEstratégia: {strat_name}")
                                for key, value in signal.items():
                                    print(f"{key}: {value}")
                                # Insere os legs do sinal no banco
                                db.insert_signal_legs(signal_id, signal, bot.asset_min_qty.get(asset, 0.01))
        except Exception as e:
            print(f"Erro na execução do robô: {e}")

        if notifications := db.check_roll_signals(roll_threshold_days=2, profit_threshold=0.75):
            print("\n=== Notificações de Rolagem ===")
            for note in notifications:
                print(note)

        # Aguarda 5 minutos antes da próxima verificação
        time.sleep(300)
