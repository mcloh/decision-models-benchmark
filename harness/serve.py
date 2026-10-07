"""Sobe um candidato em POST /v1/systemone, sem acesso à rede externa.

Uso: python -m harness.serve --candidate laya --models-root models [--device cpu] [--port 8080]
"""
import argparse

from dmb.offline import enforce_offline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--models-root", default="models")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--context-limit", type=int)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    enforce_offline()
    import uvicorn

    from dmb.server import create_app
    from harness.candidates import build_adapter

    adapter = build_adapter(args.candidate, args.models_root, args.device, args.context_limit)
    uvicorn.run(create_app(adapter), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
