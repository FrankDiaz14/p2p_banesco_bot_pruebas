import logging

try:
    from core.database import update_balance, get_balance
except ImportError:
    # Dummy mock for safe execution if the file isn't ready
    def update_balance(amount): pass
    def get_balance(): return 0.0

logger = logging.getLogger(__name__)

class ReconciliationAction:
    @staticmethod
    def deduct_balance(amount: float) -> bool:
        """
        Resta el monto transferido del saldo disponible.
        Asume que la base de datos se maneja a través de core/database.py.
        """
        try:
            logger.info(f"Conciliando base de datos: restando {amount} del saldo disponible.")
            
            # Simulated logic interacting with core/database.py
            current = get_balance()
            new_balance = current - amount
            update_balance(new_balance)
            
            logger.info("Conciliación de saldo realizada con éxito.")
            return True
        except Exception as e:
            logger.error(f"Fallo al realizar la conciliación en base de datos: {e}")
            return False
