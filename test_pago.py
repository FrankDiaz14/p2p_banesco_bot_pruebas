import asyncio
import os
from dotenv import load_dotenv
from core.browser_manager import BrowserManager
from actions.login_banesco import execute_login
from actions.transfer_banesco import execute_transfer

async def ejecutar_prueba():
    print("1. Arrancando script...")
    load_dotenv()
    print("2. Variables de entorno cargadas.")
    
    credentials = {
        "username": os.getenv("BANK_USERNAME"),
        "password": os.getenv("BANK_PASSWORD")
    }
    
    orden_de_prueba = {
        "account_number": "01340087330871068974", 
        "identity_doc": "V28651786",              
        "amount": "10,00",                        
        "concepto": "Pago"
    }
    
    print("3. Preparando para abrir el navegador...")
    async with BrowserManager() as manager:
        print("4. BrowserManager inicializado.")
        context = await manager.create_stealth_context()
        print("5. Contexto Stealth creado.")
        page = await context.new_page()
        print("6. Página en blanco abierta.")
        
        print("7. Llamando al orquestador de Login...")
        login_exitoso = await execute_login(page, credentials)
        
        if login_exitoso:
            print("8. ✅ Login exitoso retornado. Llamando a transferencias...")
            exito = await execute_transfer(context, orden_de_prueba)
            
            if exito:
                print("9. ✅ ¡TRANSFERENCIA COMPLETADA!")
            else:
                print("9. ❌ La transferencia falló.")
        else:
            print("8. ❌ Falló el inicio de sesión.")

if __name__ == '__main__':
    asyncio.run(ejecutar_prueba())