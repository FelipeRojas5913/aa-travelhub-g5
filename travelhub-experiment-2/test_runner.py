"""
Test Runner — HU023/HU024 Token Tampering Detection Experiment
Runs 8 scenarios × 3 iterations each. Results visible in Grafana.

Usage:
    pip install requests PyJWT cryptography
    python test_runner.py [--autorizador http://localhost:5001] [--reservas http://localhost:5003]
"""

import argparse
import datetime as dt
import time

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_public_key

ITERATIONS = 3

BASE_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "TestRunner/1.0",
}


def login(autorizador_url, username, password, ip=None, ua=None):
    headers = dict(BASE_HEADERS)
    if ip:
        headers["X-Forwarded-For"] = ip
    if ua:
        headers["User-Agent"] = ua
    resp = requests.post(
        f"{autorizador_url}/login",
        json={"username": username, "password": password},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_reservas(reservas_url, token, ip=None, ua=None):
    headers = {**BASE_HEADERS, "Authorization": f"Bearer {token}"}
    if ip:
        headers["X-Forwarded-For"] = ip
    if ua:
        headers["User-Agent"] = ua
    resp = requests.get(f"{reservas_url}/reservas", headers=headers, timeout=10)
    return resp


def revoke(autorizador_url, jti):
    requests.post(
        f"{autorizador_url}/revoke",
        json={"jti": jti},
        headers=BASE_HEADERS,
        timeout=10,
    )


def get_public_key_der(autorizador_url):
    resp = requests.get(f"{autorizador_url}/public-key", timeout=10)
    resp.raise_for_status()
    pem = resp.json()["public_key_pem"].encode()
    pub = load_pem_public_key(pem)
    return pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def forge_token(public_key_der, payload_overrides=None):
    payload = {
        "sub": 999,
        "role": "admin",
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        "iat": dt.datetime.now(dt.timezone.utc),
    }
    if payload_overrides:
        payload.update(payload_overrides)
    return jwt.encode(payload, public_key_der, algorithm="HS256")


def forge_expired_token(public_key_der, jti=None):
    payload = {
        "sub": 999,
        "role": "admin",
        "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1),
        "iat": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2),
    }
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, public_key_der, algorithm="HS256")


def run_scenario(fn):
    for _ in range(ITERATIONS):
        try:
            fn()
        except Exception:
            pass


def run_all(autorizador_url, reservas_url):
    public_key_der = get_public_key_der(autorizador_url)

    # Scenario 1: valid token
    def s1():
        data = login(autorizador_url, "viajero1", "pass1")
        get_reservas(reservas_url, data["token"])

    run_scenario(s1)

    # Scenario 2: forged token, no JTI
    def s2():
        token = forge_token(public_key_der)
        get_reservas(reservas_url, token)

    run_scenario(s2)

    # Scenario 3: forged token, invented JTI
    def s3():
        token = forge_token(public_key_der, {"jti": "fake-uuid-00000000-0000"})
        get_reservas(reservas_url, token)

    run_scenario(s3)

    # Scenario 4: forged token, stolen JTI, different IP/UA
    def s4():
        data = login(autorizador_url, "viajero1", "pass1",
                     ip="10.0.0.1", ua="LegitBrowser/1.0")
        token = forge_token(public_key_der, {"jti": data["jti"]})
        get_reservas(reservas_url, token, ip="192.168.99.99", ua="AttackerBot/2.0")

    run_scenario(s4)

    # Scenario 5: revoked token
    def s5():
        data = login(autorizador_url, "hotel1", "pass3")
        revoke(autorizador_url, data["jti"])
        get_reservas(reservas_url, data["token"])

    run_scenario(s5)

    # Scenario 6: expired token with valid JTI
    def s6():
        data = login(autorizador_url, "viajero1", "pass1")
        expired_token = forge_expired_token(public_key_der, jti=data["jti"])
        get_reservas(reservas_url, expired_token)

    run_scenario(s6)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--autorizador", default="http://localhost:5001")
    parser.add_argument("--reservas", default="http://localhost:5003")
    args = parser.parse_args()

    for url in [args.autorizador, args.reservas]:
        for _ in range(15):
            try:
                requests.get(f"{url}/", timeout=3)
                break
            except Exception:
                time.sleep(2)

    run_all(args.autorizador, args.reservas)


if __name__ == "__main__":
    main()
