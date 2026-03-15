import base64
import hmac as hmac_mod
import hashlib
import json as json_mod
import os
import uuid
import datetime
import time
import logging

import jwt
import psycopg2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives import serialization, hashes
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(format='\n%(asctime)s [%(name)s] %(message)s', level=logging.INFO)
logger = logging.getLogger('autorizador')

JWT_ALGORITHM = "ES256"
JWT_EXPIRATION_MINUTES = 60

MOCK_USERS = {
    "viajero1": {"password": "pass1", "user_id": 1, "role": "viajero"},
    "viajero2": {"password": "pass2", "user_id": 2, "role": "viajero"},
    "hotel1":   {"password": "pass3", "user_id": 3, "role": "hotel"},
    "admin1":   {"password": "pass4", "user_id": 4, "role": "admin"},
}

_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

PUBLIC_KEY_PEM = _PUBLIC_KEY.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

PUBLIC_KEY_DER = _PUBLIC_KEY.public_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

def _b64url_decode(s):
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * padding)


def _vulnerable_decode(token):
    parts = token.split(".")
    if len(parts) != 3:
        raise jwt.exceptions.DecodeError("Not enough segments")

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode()

    try:
        header = json_mod.loads(_b64url_decode(header_b64))
    except Exception:
        raise jwt.exceptions.DecodeError("Invalid header")

    alg = header.get("alg", "")

    try:
        signature = _b64url_decode(sig_b64)
    except Exception:
        raise jwt.exceptions.DecodeError("Invalid signature encoding")

    if alg == "HS256":
        expected = hmac_mod.new(
            PUBLIC_KEY_DER, signing_input, hashlib.sha256
        ).digest()
        if not hmac_mod.compare_digest(expected, signature):
            raise jwt.exceptions.InvalidSignatureError("Signature verification failed")

    elif alg == "ES256":
        try:
            _PUBLIC_KEY.verify(signature, signing_input, ec.ECDSA(hashes.SHA256()))
        except Exception:
            raise jwt.exceptions.InvalidSignatureError("Signature verification failed")

    else:
        raise jwt.exceptions.InvalidAlgorithmError(f"Unsupported algorithm: {alg}")

    try:
        payload = json_mod.loads(_b64url_decode(payload_b64))
    except Exception:
        raise jwt.exceptions.DecodeError("Invalid payload")

    exp = payload.get("exp")
    if exp is not None:
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if now > exp:
            raise jwt.exceptions.ExpiredSignatureError("Token has expired")

    return payload

def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=os.environ.get("DB_PORT", "5432"),
        database=os.environ.get("DB_NAME", "travelhub"),
        user=os.environ.get("DB_USER", "travelhub"),
        password=os.environ.get("DB_PASSWORD", "travelhub123"),
    )

def wait_for_db(max_retries=10, delay=3):
    for i in range(max_retries):
        try:
            conn = get_db_connection()
            conn.close()
            logger.info("Conexión a PostgreSQL exitosa")
            return True
        except Exception:
            logger.info(f"Esperando a PostgreSQL... intento {i + 1}/{max_retries}")
            time.sleep(delay)
    logger.error("No se pudo conectar a PostgreSQL")
    return False

def init_db():
    if not wait_for_db():
        raise RuntimeError("PostgreSQL no disponible")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS session_fingerprints (
            jti VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(50) NOT NULL,
            fingerprint VARCHAR(64) NOT NULL,
            ip_address VARCHAR(45),
            user_agent VARCHAR(500),
            issued_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked BOOLEAN DEFAULT FALSE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS intrusion_log (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ DEFAULT NOW(),
            scenario VARCHAR(100),
            jti_presented VARCHAR(36),
            jti_found_in_db BOOLEAN,
            fingerprint_match BOOLEAN,
            ip_address VARCHAR(45),
            user_agent VARCHAR(500),
            token_claims TEXT,
            action_taken VARCHAR(50),
            details TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("Base de datos inicializada")


def _log_intrusion(scenario, jti_presented, jti_found, fp_match,
                   ip, ua, claims, action, details):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO intrusion_log
                (scenario, jti_presented, jti_found_in_db, fingerprint_match,
                 ip_address, user_agent, token_claims, action_taken, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (scenario, jti_presented, jti_found, fp_match,
              ip, ua, str(claims), action, details))
        conn.commit()
        cur.close()
        conn.close()
        logger.warning(
            f"INTRUSION [{action}] scenario={scenario} "
            f"jti={jti_presented} details={details}"
        )
    except Exception as e:
        logger.error(f"Error registrando intrusión: {e}")

@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "autorizador", "status": "healthy"}), 200


@app.route('/public-key', methods=['GET'])
def public_key_endpoint():
    """Devuelve la clave pública en PEM (accesible por atacantes)."""
    return jsonify({"public_key_pem": PUBLIC_KEY_PEM}), 200


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing body"}), 400

    username = data.get("username")
    password = data.get("password")
    user = MOCK_USERS.get(username)

    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    jti = str(uuid.uuid4())
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    user_agent = request.headers.get("User-Agent", "")

    fingerprint = hashlib.sha256(
        f"{client_ip}:{user_agent}:{jti}".encode()
    ).hexdigest()

    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(minutes=JWT_EXPIRATION_MINUTES)

    payload = {
        "sub": user["user_id"],
        "role": user["role"],
        "jti": jti,
        "iat": now,
        "exp": expires_at,
    }

    token = jwt.encode(payload, _PRIVATE_KEY, algorithm=JWT_ALGORITHM)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO session_fingerprints
                (jti, user_id, fingerprint, ip_address, user_agent, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (jti, str(user["user_id"]), fingerprint,
              client_ip, user_agent, expires_at))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error almacenando fingerprint: {e}")
        return jsonify({"error": "Internal error"}), 500

    return jsonify({"token": token, "jti": jti}), 200


@app.route('/validate', methods=['POST'])
def validate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing body"}), 400

    token = data.get("token")
    if not token:
        return jsonify({"error": "Missing token"}), 400

    client_ip = data.get("client_ip",
                         request.headers.get("X-Forwarded-For", request.remote_addr))
    client_ua = data.get("client_ua", request.headers.get("User-Agent", ""))

    try:
        decoded = _vulnerable_decode(token)
    except jwt.exceptions.ExpiredSignatureError:
        return jsonify({"error": "Token expired", "jwt_validation": "EXPIRED"}), 401
    except (jwt.exceptions.DecodeError,
            jwt.exceptions.InvalidSignatureError,
            jwt.exceptions.InvalidAlgorithmError) as e:
        return jsonify({"error": str(e), "jwt_validation": "FAILED"}), 401

    jti = decoded.get("jti")

    if not jti:
        _log_intrusion("NO_JTI", None, False, False,
                       client_ip, client_ua, decoded, "BLOCKED",
                       "Token sin campo JTI")
        return jsonify({
            "valid": False, "blocked": True,
            "jwt_validation": "PASSED", "fingerprint_validation": "FAILED",
            "reason": "Token has no JTI field",
        }), 401

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT jti, fingerprint, revoked FROM session_fingerprints WHERE jti = %s",
            (jti,),
        )
        session_row = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error consultando sesión: {e}")
        return jsonify({"error": "Internal error"}), 500

    if not session_row:
        _log_intrusion("JTI_NOT_FOUND", jti, False, False,
                       client_ip, client_ua, decoded, "BLOCKED",
                       "JTI no existe en BD")
        return jsonify({
            "valid": False, "blocked": True,
            "jwt_validation": "PASSED", "fingerprint_validation": "FAILED",
            "reason": "JTI not found in session store",
        }), 401

    _, fingerprint_db, revoked = session_row

    if revoked:
        _log_intrusion("REVOKED_TOKEN", jti, True, None,
                       client_ip, client_ua, decoded, "BLOCKED",
                       "Sesión revocada")
        return jsonify({
            "valid": False, "blocked": True,
            "jwt_validation": "PASSED", "fingerprint_validation": "FAILED",
            "reason": "Session revoked",
        }), 401

    current_fp = hashlib.sha256(
        f"{client_ip}:{client_ua}:{jti}".encode()
    ).hexdigest()

    if current_fp != fingerprint_db:
        _log_intrusion("FINGERPRINT_MISMATCH", jti, True, False,
                       client_ip, client_ua, decoded, "BLOCKED",
                       f"expected={fingerprint_db[:16]}… actual={current_fp[:16]}…")
        return jsonify({
            "valid": False, "blocked": True,
            "jwt_validation": "PASSED", "fingerprint_validation": "FAILED",
            "reason": "Session fingerprint mismatch",
        }), 401

    return jsonify({
        "valid": True,
        "jwt_validation": "PASSED",
        "fingerprint_validation": "PASSED",
        "claims": decoded,
    }), 200


@app.route('/revoke', methods=['POST'])
def revoke():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing body"}), 400

    jti = data.get("jti")
    if not jti:
        return jsonify({"error": "Missing jti"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE session_fingerprints SET revoked = TRUE WHERE jti = %s",
            (jti,),
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if updated == 0:
            return jsonify({"error": "JTI not found"}), 404
        return jsonify({"revoked": True, "jti": jti}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5001)
