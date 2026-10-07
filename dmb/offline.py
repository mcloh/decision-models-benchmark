"""Isolamento de rede dentro do processo (tarefa 19, camada de aplicação).

A camada de rede (VCN sem rota de saída) é a garantia principal; esta camada faz o
processo falhar de forma explícita se um candidato tentar abrir conexão externa.
"""
from __future__ import annotations

import ipaddress
import os
import socket

OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "USE_TF": "0",
}


class NetworkAccessBlocked(RuntimeError):
    pass


def _is_local(address) -> bool:
    if isinstance(address, tuple):
        host = address[0]
    else:
        return True  # sockets AF_UNIX
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def enforce_offline() -> None:
    os.environ.update(OFFLINE_ENV)
    if getattr(socket.socket.connect, "_dmb_guard", False):
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address):
        if not _is_local(address):
            raise NetworkAccessBlocked(f"conexão externa bloqueada durante o benchmark: {address}")
        return original_connect(self, address)

    def guarded_connect_ex(self, address):
        if not _is_local(address):
            raise NetworkAccessBlocked(f"conexão externa bloqueada durante o benchmark: {address}")
        return original_connect_ex(self, address)

    guarded_connect._dmb_guard = True
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex


def self_test() -> dict:
    """Prova, dentro do processo, que o bloqueio está ativo: uma conexão externa tem de falhar."""
    probe = socket.socket()
    try:
        probe.connect(("pypi.org", 443))
        return {"process_guard": "FALHOU: conexão externa aberta"}
    except NetworkAccessBlocked:
        return {"process_guard": "ok"}
    except OSError as error:  # sem rede nenhuma: também prova que não há saída
        return {"process_guard": f"ok (rede indisponível: {type(error).__name__})"}
    finally:
        probe.close()
