import os
import time
import hmac
import hashlib
import urllib.parse
import requests
import dotenv

dotenv.load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

class BinanceP2P:
    def __init__(self):
        self.base_url = "https://api.binance.com"
        self.api_key = BINANCE_API_KEY
        self.secret_key = BINANCE_SECRET_KEY
        
        self.headers = {
            "X-MBX-APIKEY": self.api_key
        }

    def _hashing(self, query_string):
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def get_pending_buy_orders(self):
        endpoint = "/sapi/v1/c2c/orderMatch/listUserOrderHistory"
        params = {
            "tradeType": "BUY",
            "timestamp": int(time.time() * 1000)
        }
        
        query_string = urllib.parse.urlencode(params)
        signature = self._hashing(query_string)
        
        url = f"{self.base_url}{endpoint}?{query_string}&signature={signature}"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json().get('data', [])
            
            pending_orders = [
                order for order in data 
                if order.get('orderStatus') == 'PENDING'
            ]
            return pending_orders
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching Binance orders: {e}")
            raise

    def extract_banesco_data(self, order):
        return {
            "orderNumber": order.get("orderNumber"),
            "amount": order.get("amount"),
            "payMethods": order.get("payMethods", [])
        }

    def mark_order_as_paid(self, order_id):
        endpoint = "/sapi/v1/c2c/orderMatch/payOrder"
        params = {
            "orderNumber": order_id,
            "timestamp": int(time.time() * 1000)
        }
        
        query_string = urllib.parse.urlencode(params)
        signature = self._hashing(query_string)
        
        url = f"{self.base_url}{endpoint}?{query_string}&signature={signature}"
        
        try:
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
            print(f"Order {order_id} marked as paid successfully.")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error marking order {order_id} as paid: {e}")
            return False
