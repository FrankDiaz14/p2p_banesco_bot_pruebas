"""
Módulo de Ofuscación y Simulación Orgánica.

Provee utilidades asíncronas y matemáticas para simular comportamientos humanos 
(antropomórficos) durante la automatización e interacciones en navegadores.
El objetivo principal es evadir heurísticas y sistemas anti-bot introduciendo
ruido estadístico, retrasos orgánicos y movimientos no lineales.
"""

import asyncio
import secrets
from typing import AsyncGenerator, List, Tuple

# Utilizamos SystemRandom para generar números con mayor entropía criptográfica.
# Esto dificulta el análisis estadístico de los sistemas anti-bot al depender
# de fuentes de aleatoriedad del sistema operativo y no del reloj.
secure_random = secrets.SystemRandom()


async def organic_delay() -> None:
    """
    Suspende la ejecución actual con un retraso pseudoaleatorio prolongado.
    
    Mitigación Anti-Bot:
        Evita que las transiciones entre páginas, envíos de formularios o 
        clicks ocurran instantáneamente. Simula el tiempo cognitivo y visual
        que le tomaría a un usuario humano real leer un SMS, verificar un monto 
        en pantalla o procesar información antes de realizar una acción crítica.
        
    El tiempo de pausa varía de forma flotante entre 32.0 y 45.0 segundos.
    """
    # Rango especificado: entre 32.0 y 45.0 segundos
    delay: float = secure_random.uniform(32.0, 45.0)
    await asyncio.sleep(delay)


async def human_typing(texto: str) -> AsyncGenerator[str, None]:
    """
    Generador asíncrono que simula la cadencia de tipeo de un usuario humano.
    
    Mitigación Anti-Bot:
        Evita la inyección de texto instantánea (copy-paste robótico) en campos 
        de entrada (inputs). Los sistemas de seguridad bancaria miden el 
        'Keystroke Dynamics'; esta función puramente matemática introduce un 
        delta de tiempo aleatorio orgánico entre cada pulsación de tecla.
        
    Args:
        texto (str): La cadena de texto que se desea tipear de forma humana.
        
    Yields:
        str: El carácter actual de la iteración, retornado en el tiempo correcto.
             (Para ser inyectado por el orquestador ej. page.keyboard.press(char))
    """
    for char in texto:
        # Retraso aleatorio estricto entre 100ms (0.1s) y 250ms (0.25s) por pulsación
        delay: float = secure_random.uniform(0.100, 0.250)
        await asyncio.sleep(delay)
        yield char


def _get_random_control_point(
    start: Tuple[float, float], 
    end: Tuple[float, float], 
    deviation_factor: float = 0.4
) -> Tuple[float, float]:
    """
    Calcula un punto de control aleatorio (ruido) que desvía la trayectoria de una línea recta.
    
    Args:
        start (Tuple[float, float]): Coordenada inicial (x, y).
        end (Tuple[float, float]): Coordenada final (x, y).
        deviation_factor (float): Magnitud de alejamiento del punto medio euclidiano.
        
    Returns:
        Tuple[float, float]: Coordenadas del punto de control perturbado.
    """
    x1, y1 = start
    x2, y2 = end
    
    # Se calcula el punto medio exacto de la recta
    mid_x, mid_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    
    # La desviación escala dinámicamente según la distancia total entre inicio y destino
    distance = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    
    # Se añade un offset aleatorio para el punto de control
    offset_x = secure_random.uniform(-1.0, 1.0) * distance * deviation_factor
    offset_y = secure_random.uniform(-1.0, 1.0) * distance * deviation_factor
    
    return (mid_x + offset_x, mid_y + offset_y)


def generate_mouse_curve(
    start_point: Tuple[float, float], 
    end_point: Tuple[float, float],
    num_points: int = 40
) -> List[Tuple[float, float]]:
    """
    Genera una trayectoria curva utilizando Curvas de Bézier Cuadráticas con ruido.
    
    Mitigación Anti-Bot:
        Los bots primitivos mueven el cursor de manera rectilínea euclidiana o 
        se teletransportan al objetivo. Esta función interpola matemáticamente una 
        ruta curva imperfecta con un punto de atracción aleatorio, simulando 
        la inercia y biomecánica natural de la mano humana sobre el ratón.
        
    Args:
        start_point (Tuple[float, float]): Coordenadas iniciales de partida (x, y).
        end_point (Tuple[float, float]): Coordenadas finales del objetivo (x, y).
        num_points (int): Cantidad de píxeles/puntos a interpolar a lo largo del trazo.
        
    Returns:
        List[Tuple[float, float]]: Colección de puntos que estructuran la trayectoria orgánica.
    """
    x0, y0 = start_point
    x2, y2 = end_point
    
    # Generamos un punto de control para torcer la trayectoria de la curva
    cp_x, cp_y = _get_random_control_point(start_point, end_point)
    
    curve_points: List[Tuple[float, float]] = []
    
    for i in range(num_points + 1):
        # Escalar el paso t normalizado [0.0, 1.0]
        t = i / float(num_points) if num_points > 0 else 1.0
        
        # Función polinomial de Curva de Bézier Cuadrática pura:
        # B(t) = (1-t)^2 * P0 + 2(1-t)t * P1 + t^2 * P2
        term0 = (1.0 - t) ** 2
        term1 = 2.0 * (1.0 - t) * t
        term2 = t ** 2
        
        xt = (term0 * x0) + (term1 * cp_x) + (term2 * x2)
        yt = (term0 * y0) + (term1 * cp_y) + (term2 * y2)
        
        curve_points.append((xt, yt))
        
    return curve_points