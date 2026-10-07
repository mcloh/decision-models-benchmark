"""Atualiza o bloco de andamento de docs/03-plano-de-tarefas.md a partir das caixas de cada tarefa.

Legenda: [x] concluída · [~] em andamento/parcial · [ ] pendente.
Uso: python tools/plan_progress.py
"""
import re
from datetime import date
from pathlib import Path

PLAN = Path(__file__).resolve().parents[1] / "docs" / "03-plano-de-tarefas.md"
START, END = "<!-- PROGRESSO:INICIO -->", "<!-- PROGRESSO:FIM -->"


def main():
    text = PLAN.read_text()
    phases, current = [], None
    for line in text.splitlines():
        if line.startswith("## F"):
            current = [line[3:].strip(), 0, 0, 0]
            phases.append(current)
        m = re.match(r"- \[(x| |~)\] \*\*\d+\.\*\*", line)
        if m and current:
            current[{"x": 1, "~": 2, " ": 3}[m.group(1)]] += 1
    rows = ["| Fase | Concluídas | Em andamento | Pendentes |", "|------|-----------|--------------|-----------|"]
    totals = [0, 0, 0]
    for name, done, doing, todo in phases:
        rows.append(f"| {name} | {done} | {doing} | {todo} |")
        totals = [totals[0] + done, totals[1] + doing, totals[2] + todo]
    rows.append(f"| **Total** | **{totals[0]}** | **{totals[1]}** | **{totals[2]}** |")
    block = (f"{START}\n**Andamento em {date.today():%Y-%m-%d}:** {totals[0]} de {sum(totals)} tarefas concluídas "
             f"({100 * totals[0] // sum(totals)}%), {totals[1]} em andamento.\n\n" + "\n".join(rows)
             + "\n\nLegenda: `[x]` concluída · `[~]` em andamento ou parcial · `[ ]` pendente.\n" + END)
    if START in text:
        text = re.sub(re.escape(START) + ".*?" + re.escape(END), block, text, flags=re.S)
    else:
        text = text.replace("\n---\n", f"\n{block}\n\n---\n", 1)
    PLAN.write_text(text)
    print(block)


if __name__ == "__main__":
    main()
