# 3rd Party Libraries
import pytz
import time
import random
import logging
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

# Configuración del logger
logging.basicConfig(format = '\n%(asctime)s %(message)s', datefmt = '%Y-%m-%d %H:%M:%S %p: ', level = logging.INFO)
logger = logging.getLogger('inventario')

# Instanciar app
app = Flask(__name__)

# Establecer el servicio intento del servicio
service_state = {"status": "healthy", "delay": 0}

def random_failure():
    """Simula fallos y degradaciones aleatorias"""
    
    # Generar un número aleatorio entre 0 y 1
    roll = random.random()

    # En caso de que el número sea menor a 0.3
    if roll < 0.3:
        
        # Actualizar el status a degraded
        service_state["status"] = "degraded"

        # Establecer una demora aleatoria entre 2 y 5 segundos
        service_state["delay"] = random.uniform(2, 5)

        # Imprimir mensaje de log
        logger.info(f"inventario -> DEGRADED (delay: {service_state['delay']:.1f}s)")

    # En caso de que el número sea menor a 0.5
    elif roll < 0.5:
        
        # Actualizar el status a unhealthy
        service_state["status"] = "unhealthy"

        # Establecer una demora de 0
        service_state["delay"] = 0

        # Imprimir mensaje de log
        logger.info(f"inventario -> UNHEALTHY")

    # Con un roll superior a 0.5
    else:

        # Actualizar el status a healthy
        service_state["status"] = "healthy"

        # Establecer una demora de 0
        service_state["delay"] = 0

        # Imprimir mensaje de log
        logger.info(f"inventario -> HEALTHY")

# Instanciar el cronjob
scheduler = BackgroundScheduler()

# Programar el cronjob cada 15-30 segundos
scheduler.add_job(random_failure, 'interval', seconds = random.randint(15, 30))

# Iniciar el cronjob
scheduler.start()

# Api de Health
@app.route('/inventario/health', methods = ['GET'])
def health():
    """Permite consultar el estado del servicio"""

    # Si el servicio está unhealthy, retornar un código de estado 500
    if service_state["status"] == "unhealthy":
        return jsonify({"service": "inventario", "status": "unhealthy", "timestamp": datetime.now(pytz.timezone('America/Bogota')).strftime('%Y-%m-%d %H:%M:%S %Z')}), 500

    # Si el servicio está degraded, esperar el tiempo de demora
    elif service_state["status"] == "degraded":
        time.sleep(service_state["delay"])

    # Retornar un código de estado 200
    return jsonify({"service": "inventario", "status": service_state["status"], "timestamp": datetime.now(pytz.timezone('America/Bogota')).strftime('%Y-%m-%d %H:%M:%S %Z')}), 200
    
# Iniciar servicio
if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5001, debug = True)