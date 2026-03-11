import os
import datetime

import jwt
from flask import Flask, request, jsonify, Response
import requests

app = Flask(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 60

MOCK_USERS = {
    "viajero1": {"password": "pass1", "user_id": 1, "role": "viajero"},
    "viajero2": {"password": "pass2", "user_id": 2, "role": "viajero"},
    "hotel1":   {"password": "pass3", "user_id": 3, "role": "hotel"},
    "admin1":   {"password": "pass4", "user_id": 4, "role": "admin"},
}

def forward_request(service_url, path):
    url = f"{service_url}/{path}"

    resp = requests.request(
        method=request.method,
        url=url,
        headers={key: value for key, value in request.headers if key != 'Host'},
        params=request.args,
        json=request.get_json(silent=True),
    )

    return Response(
        resp.content,
        status=resp.status_code,
        content_type=resp.headers.get('Content-Type')
    )

@app.route("/API/<path:path>", methods=["GET","POST","PUT","DELETE"])
def log(path):
    return forward_request("http://localhost:8001/", path)


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing body"}), 400

    username = data.get("username")
    password = data.get("password")
    user = MOCK_USERS.get(username)

    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user["user_id"],
        "role": user["role"],
        "iat": now,
        "exp": now + datetime.timedelta(minutes=JWT_EXPIRATION_MINUTES),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return jsonify({"token": token}), 200


@app.route("/validate", methods=["POST"])
def validate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing body"}), 400

    token = data.get("token")
    if not token:
        return jsonify({"error": "Missing token"}), 400

    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return jsonify({"valid": True, "claims": claims}), 200
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError as e:
        return jsonify({"error": f"Invalid token: {str(e)}"}), 401


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
