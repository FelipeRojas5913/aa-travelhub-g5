# 3rd Party Libraries
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request

# Instanciar app
app = Flask(__name__)

# Establecer el servicio intento del servicio
service_state = {"status": "healthy", "delay": 0}

# Api de Health
@app.route('/health', methods = ['GET'])
def health():
    """Permite consultar el estado del servicio"""

    # En caso de que se encuentre "unhealthy", se devuelve un código de estado 500
    if service_state["status"] == "unhealthy":
        return jsonify({"service": "ordenes", "status": "unhealthy"}), 500
    
    # En caso de estar "degraded", agrega latencia artificial
    elif service_state["status"] == "degraded":
        time.sleep(service_state["delay"])
    
    # En caso de que se encuentre "healthy", se devuelve un código de estado 200
    else:
        return jsonify({"service": "ordenes", "status": service_state["status"], "timestamp": datetime.now(timezone.utc)}), 200
    
# Iniciar servicio
if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5002, debug = True)