import ccxt
import time
import sqlite3
import json
from datetime import datetime, timedelta

class SignalDatabase:
    def __init__(self, db_name="signals.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_table()
    
    def create_table(self):
        cursor = self.conn.cursor()
        cursor.execute('''
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
        ''')
        self.conn.commit()
    
    def insert_signal(self, asset, strategy, expiration, premium, signal_details, roll_instruction):
        if self.signal_exists(asset, strategy, expiration):
            print(f"Sinal para {asset} - {strategy} com expiração {expiration} já existe. Ignorando duplicata.")
            return
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO signals (asset, strategy, expiration, premium, signal_details, roll_instruction)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (asset, strategy, expiration, premium, json.dumps(signal_details), roll_instruction))
        self.conn.commit()
    
    def signal_exists(self, asset, strategy, expiration):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM signals WHERE asset=? AND strategy=? AND expiration=? AND status='active'",
                       (asset, strategy, expiration))
        row = cursor.fetchone()
        return row is not None
    
    def check_roll_signals(self, roll_threshold_days=2, profit_threshold=0.75):
        """
        Verifica sinais ativos e gera notificações se:
          - A expiração estiver a <= roll_threshold_days a partir de agora, OU
          - A fração de tempo decorrido (simulada como proxy do lucro) for >= profit_threshold.
        Após notificar, atualiza o status do sinal para evitar notificações repetidas.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, asset, strategy, expiration, premium, roll_instruction, timestamp FROM signals WHERE status = 'active'")
        rows = cursor.fetchall()
        notifications = []
        now = datetime.now()
        for row in rows:
            signal_id, asset, strategy, expiration, premium, roll_instruction, entry_timestamp = row
            try:
                exp_date = datetime.strptime(expiration, "%Y-%m-%d")
                entry_date = datetime.strptime(entry_timestamp, "%Y-%m-%d %H:%M:%S")
            except Exception as e:
                continue
            
            time_to_exp = exp_date - now
            notify_exp = time_to_exp <= timedelta(days=roll_threshold_days)
            
            total_time = exp_date - entry_date
            elapsed = now - entry_date
            profit_fraction = elapsed.total_seconds() / total_time.total_seconds() if total_time.total_seconds() > 0 else 0
            notify_profit = profit_fraction >= profit_threshold
            
            if notify_exp or notify_profit:
                if notify_exp and notify_profit:
                    message = (f"Signal ID {signal_id} ({asset} - {strategy}) está próximo da expiração ({expiration}) "
                               f"e atingiu {profit_fraction*100:.1f}% do tempo decorrido. "
                               f"Instrução de Rolagem: {roll_instruction}")
                elif notify_exp:
                    message = (f"Signal ID {signal_id} ({asset} - {strategy}) está próximo da expiração ({expiration}). "
                               f"Instrução de Rolagem: {roll_instruction}")
                else:
                    message = (f"Signal ID {signal_id} ({asset} - {strategy}) atingiu {profit_fraction*100:.1f}% do tempo decorrido "
                               f"(indicativo de lucro máximo). Instrução de Rolagem: {roll_instruction}")
                notifications.append(message)
                cursor.execute("UPDATE signals SET status = 'rolled' WHERE id = ?", (signal_id,))
        self.conn.commit()
        return notifications

class OptionStrategyBot:
    def __init__(self, api_key=None, secret=None, quote_currency="USDT"):
        """
        Inicializa o robô para a Bybit via ccxt.
        Se as credenciais não forem fornecidas, usa apenas endpoints públicos.
        """
        self.quote_currency = quote_currency
        if api_key and secret:
            self.exchange = ccxt.bybit({
                'apiKey': api_key,
                'secret': secret,
            })
        else:
            self.exchange = ccxt.bybit()  # Apenas dados públicos
        
        self.assets = ['BTC', 'ETH', 'SOL']
        self.iv_threshold = 0.50
        self.default_qty = 0.01  # Quantidade padrão por perna

    def fetch_underlying_price(self, asset):
        symbol = f"{asset}/{self.quote_currency}"
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            print(f"Erro ao buscar ticker para {symbol}: {e}")
            return None

    def fetch_options_data(self, asset):
        """
        Simula a obtenção de dados de opções para o ativo.
        Retorna um dicionário com:
          - 'expirations': lista de datas de vencimento disponíveis;
          - 'calls': opções de compra com strike, IV e símbolo;
          - 'puts': opções de venda com strike, IV e símbolo.
        """
        underlying_price = self.fetch_underlying_price(asset)
        if underlying_price is None:
            underlying_price = 0
        
        simulated_data = {
            'expirations': ['2025-03-30', '2025-04-06'],
            'calls': [
                {'strike': 1.10 * underlying_price, 'iv': 0.60, 'symbol': f'{asset}_CALL_OTM1'},
                {'strike': 1.15 * underlying_price, 'iv': 0.55, 'symbol': f'{asset}_CALL_OTM2'}
            ],
            'puts': [
                {'strike': 0.90 * underlying_price, 'iv': 0.65, 'symbol': f'{asset}_PUT_OTM1'},
                {'strike': 0.85 * underlying_price, 'iv': 0.70, 'symbol': f'{asset}_PUT_OTM2'}
            ]
        }
        return simulated_data

    def analyze_and_generate_short_strangle(self, asset):
        price = self.fetch_underlying_price(asset)
        if price is None:
            return {"strategy": "Erro", "rationale": f"Não foi possível obter o preço de {asset}"}, ""
        
        print(f"\nAnalisando Short Strangle para {asset}: preço atual = {price:.2f} {self.quote_currency}")
        options_data = self.fetch_options_data(asset)
        expiration = options_data.get('expirations', [None])[0]
        otm_calls = [op for op in options_data['calls'] if op['strike'] > price]
        otm_puts = [op for op in options_data['puts'] if op['strike'] < price]
        
        # Cálculo dos prêmios simulados para cada perna (fórmula arbitrária: IV * preço * 0.01)
        if otm_calls and otm_puts:
            call_to_sell = min(otm_calls, key=lambda x: x['strike'])
            put_to_sell = max(otm_puts, key=lambda x: x['strike'])
            premium_call = call_to_sell['iv'] * price * 0.01
            premium_put = put_to_sell['iv'] * price * 0.01
            total_premium = premium_call + premium_put
            
            # Lógica de ajuste de quantidade:
            sell_call_qty = self.default_qty
            sell_put_qty = self.default_qty
            if premium_call > premium_put * 1.1:
                sell_call_qty = self.default_qty * 1.5
            elif premium_put > premium_call * 1.1:
                sell_put_qty = self.default_qty * 1.5
            
            if (call_to_sell['iv'] + put_to_sell['iv']) / 2.0 > self.iv_threshold:
                roll_instruction = "Fechar posições e montar novo Short Strangle para a próxima expiração."
                # Acrescenta a quantidade nas informações de cada perna
                call_to_sell.update({"quantity": sell_call_qty})
                put_to_sell.update({"quantity": sell_put_qty})
                signal = {
                    "strategy": "Short Strangle",
                    "sell_call": call_to_sell,
                    "sell_put": put_to_sell,
                    "expiration": expiration,
                    "premium": total_premium,
                    "rationale": (f"IV média acima do limiar. Prêmios: call={premium_call:.4f}, put={premium_put:.4f}.")
                }
            else:
                roll_instruction = ""
                signal = {
                    "strategy": "No Trade - Short Strangle",
                    "expiration": expiration,
                    "premium": total_premium,
                    "rationale": (f"IV média abaixo do limiar. Prêmios: call={premium_call:.4f}, put={premium_put:.4f}.")
                }
        else:
            roll_instruction = ""
            signal = {
                "strategy": "No Trade - Short Strangle",
                "expiration": expiration,
                "premium": 0,
                "rationale": "Opções OTM não disponíveis."
            }
        return signal, roll_instruction

    def analyze_and_generate_bull_call_spread(self, asset):
        price = self.fetch_underlying_price(asset)
        if price is None:
            return {"strategy": "Erro", "rationale": f"Não foi possível obter o preço de {asset}"}, ""
        
        print(f"\nAnalisando Bull Call Spread para {asset}: preço atual = {price:.2f} {self.quote_currency}")
        options_data = self.fetch_options_data(asset)
        expiration = options_data.get('expirations', [None])[0]
        calls = options_data['calls']
        
        if len(calls) >= 2:
            sorted_calls = sorted(calls, key=lambda x: x['strike'])
            sold_call = next((op for op in sorted_calls if op['strike'] > price), None)
            if sold_call is None:
                return {"strategy": "No Trade - Bull Call Spread",
                        "rationale": "Nenhuma call OTM disponível.", "expiration": expiration, "premium": 0}, ""
            index = sorted_calls.index(sold_call)
            if index + 1 < len(sorted_calls):
                bought_call = sorted_calls[index + 1]
            else:
                return {"strategy": "No Trade - Bull Call Spread",
                        "rationale": "Não há call para proteção.", "expiration": expiration, "premium": 0}, ""
            
            sold_call_premium = sold_call['iv'] * price * 0.005
            bought_call_cost = bought_call['iv'] * price * 0.005
            net_credit = max(0, sold_call_premium - bought_call_cost)
            
            # Se o crédito for alto, aumentamos a quantidade de ambos os lados (spread deve ser 1:1)
            qty = self.default_qty
            if net_credit > price * 0.001:
                qty = self.default_qty * 1.5
            
            sold_call.update({"quantity": qty})
            bought_call.update({"quantity": qty})
            roll_instruction = "Fechar a trava de alta e montar nova trava para a próxima expiração."
            signal = {
                "strategy": "Bull Call Spread",
                "sell_call": sold_call,
                "buy_call": bought_call,
                "expiration": expiration,
                "premium": net_credit,
                "rationale": (f"Crédito líquido: {net_credit:.4f}.")
            }
        else:
            roll_instruction = ""
            signal = {
                "strategy": "No Trade - Bull Call Spread",
                "expiration": expiration,
                "premium": 0,
                "rationale": "Dados insuficientes de opções."
            }
        return signal, roll_instruction

    def analyze_and_generate_bear_put_spread(self, asset):
        price = self.fetch_underlying_price(asset)
        if price is None:
            return {"strategy": "Erro", "rationale": f"Não foi possível obter o preço de {asset}"}, ""
        
        print(f"\nAnalisando Bear Put Spread para {asset}: preço atual = {price:.2f} {self.quote_currency}")
        options_data = self.fetch_options_data(asset)
        expiration = options_data.get('expirations', [None])[0]
        puts = options_data['puts']
        
        if len(puts) >= 2:
            sorted_puts = sorted(puts, key=lambda x: x['strike'], reverse=True)
            sold_put = next((op for op in sorted_puts if op['strike'] < price), None)
            if sold_put is None:
                return {"strategy": "No Trade - Bear Put Spread",
                        "rationale": "Nenhuma put OTM disponível.", "expiration": expiration, "premium": 0}, ""
            index = sorted_puts.index(sold_put)
            if index + 1 < len(sorted_puts):
                bought_put = sorted_puts[index + 1]
            else:
                return {"strategy": "No Trade - Bear Put Spread",
                        "rationale": "Não há put para proteção.", "expiration": expiration, "premium": 0}, ""
            
            sold_put_premium = sold_put['iv'] * price * 0.005
            bought_put_cost = bought_put['iv'] * price * 0.005
            net_credit = max(0, sold_put_premium - bought_put_cost)
            
            qty = self.default_qty
            if net_credit > price * 0.001:
                qty = self.default_qty * 1.5
            
            sold_put.update({"quantity": qty})
            bought_put.update({"quantity": qty})
            roll_instruction = "Fechar a trava de baixa e montar nova trava para a próxima expiração."
            signal = {
                "strategy": "Bear Put Spread",
                "sell_put": sold_put,
                "buy_put": bought_put,
                "expiration": expiration,
                "premium": net_credit,
                "rationale": (f"Crédito líquido: {net_credit:.4f}.")
            }
        else:
            roll_instruction = ""
            signal = {
                "strategy": "No Trade - Bear Put Spread",
                "expiration": expiration,
                "premium": 0,
                "rationale": "Dados insuficientes de opções."
            }
        return signal, roll_instruction

    def run(self):
        signals = {}
        for asset in self.assets:
            print(f"\n=== Análise do ativo: {asset}/{self.quote_currency} ===")
            short_strangle, roll_instruction_strangle = self.analyze_and_generate_short_strangle(asset)
            bull_call, roll_instruction_bull = self.analyze_and_generate_bull_call_spread(asset)
            bear_put, roll_instruction_bear = self.analyze_and_generate_bear_put_spread(asset)
            signals[asset] = {
                "short_strangle": (short_strangle, roll_instruction_strangle),
                "bull_call_spread": (bull_call, roll_instruction_bull),
                "bear_put_spread": (bear_put, roll_instruction_bear)
            }
            time.sleep(1)
        return signals

# Execução contínua do robô com armazenamento e monitoramento de sinais
if __name__ == '__main__':
    API_KEY = None
    API_SECRET = None
    
    bot = OptionStrategyBot(API_KEY, API_SECRET, quote_currency="USDT")
    db = SignalDatabase("signals.db")
    
    while True:
        try:
            results = bot.run()
            print("\n=== Sinais de Entrada Gerados ===")
            for asset, strategies in results.items():
                print(f"\nAtivo: {asset}/{bot.quote_currency}")
                for strat_name, (signal, roll_instruction) in strategies.items():
                    print(f"\nEstratégia: {strat_name}")
                    for key, value in signal.items():
                        print(f"{key}: {value}")
                    # Insere sinal somente se não for "No Trade" ou "Erro"
                    if "No Trade" not in signal["strategy"] and "Erro" not in signal["strategy"]:
                        db.insert_signal(asset, signal["strategy"], signal.get("expiration", ""), 
                                         signal.get("premium", 0), signal, roll_instruction)
        except Exception as e:
            print(f"Erro na execução do robô: {e}")
        
        # Verifica sinais para rolagem (por expiração próxima ou lucro maximizado)
        notifications = db.check_roll_signals(roll_threshold_days=2, profit_threshold=0.75)
        if notifications:
            print("\n=== Notificações de Rolagem ===")
            for note in notifications:
                print(note)
        
        # Aguarda 5 minutos antes da próxima verificação
        time.sleep(300)
