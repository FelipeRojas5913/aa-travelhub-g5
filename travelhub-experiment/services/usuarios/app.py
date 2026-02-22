# 3rd Party Libraries
import pytz
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request

# Instanciar app
app = Flask(__name__)

# Establecer el servicio intento del servicio
service_state = {"status": "healthy", "delay": 0}

# Api de Health
@app.route('/usuarios/health', methods = ['GET'])
def health():
    """Permite consultar el estado del servicio"""

    # Retornar un código de estado 200
    return jsonify({"service": "usuarios", "status": service_state["status"], "timestamp": datetime.now(pytz.timezone('America/Bogota')).strftime('%Y-%m-%d %H:%M:%S %Z')}), 200

# Iniciar servicio
if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5004, debug = True)