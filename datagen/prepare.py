"""Mascaramento, deduplicação e critérios de inclusão antes da anotação (tarefas 25 e 28).

Uso: python -m datagen.prepare --run /data/runs/datagen-v1
Entrada: generated.jsonl. Saída: candidates.jsonl + prepare-report.json.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

# Ordem importa: padrões mais longos primeiro.
PII_PATTERNS = [
    ("<CARTAO>", re.compile(r"\b\d{4}[ .-]?\d{4}[ .-]?\d{4}[ .-]?\d{4}\b")),
    ("<CNPJ>", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    ("<CPF>", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("<EMAIL>", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("<TELEFONE>", re.compile(r"(?:\+?55\s?)?\(?\b\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}\b")),
    ("<CEP>", re.compile(r"\b\d{5}-\d{3}\b")),
]
MIN_CHARS, MAX_CHARS = 2, 700
NEAR_DUP_JACCARD = 0.85


def mask(text: str) -> tuple[str, list[str]]:
    found = []
    for token, pattern in PII_PATTERNS:
        text, n = pattern.subn(token, text)
        found += [token] * n
    return text, found


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w<> ]", " ", text)).strip()


def shingles(text: str, k: int = 5) -> frozenset:
    return frozenset(text[i:i + k] for i in range(max(1, len(text) - k + 1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    run = Path(args.run)
    rows = [json.loads(l) for l in (run / "generated.jsonl").open()]
    report = Counter()
    kept, seen_exact, kept_shingles = [], set(), []
    for r in rows:
        text, found = mask(r["text"])
        report["pii_masked"] += len(found)
        if not (MIN_CHARS <= len(text) <= MAX_CHARS):
            report["excluded_length"] += 1
            continue
        norm = normalize(text)
        if norm in seen_exact:
            report["excluded_exact_dup"] += 1
            continue
        sh = shingles(norm)
        if any(len(sh & o) / len(sh | o) >= NEAR_DUP_JACCARD for o in kept_shingles
               if abs(len(o) - len(sh)) <= 0.3 * len(sh)):
            report["excluded_near_dup"] += 1
            continue
        seen_exact.add(norm)
        kept_shingles.append(sh)
        kept.append({**r, "text": text, "pii_masked": found})
    with (run / "candidates.jsonl").open("w") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report.update(generated=len(rows), kept=len(kept))
    (run / "prepare-report.json").write_text(json.dumps(dict(report), indent=2) + "\n")
    print(json.dumps(dict(report)))


if __name__ == "__main__":
    main()
