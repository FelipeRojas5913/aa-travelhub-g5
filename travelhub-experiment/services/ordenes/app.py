# 3rd Party Libraries
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request

# Instanciar app
app = Flask(__name__)

# Establecer el servicio intento del servicio
service_state = {"status": "healthy", "delay": 0}

# Api de Health
@app.route('/ordenes/health', methods = ['GET'])
def health():
    """Permite consultar el estado del servicio"""

    # Retornar un código de estado 200
    return jsonify({"service": "ordenes", "status": service_state["status"], "timestamp": datetime.now(timezone.utc)}), 200
    
# Iniciar servicio
if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5002, debug = True)