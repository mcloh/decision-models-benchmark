from dmb.canonical import fit_state, serialize_state, to_jev_request

STATE = {
    "active_agent": "agente_a",
    "suspended_sessions": ["agente_b"],
    "recent_turns": [
        {"role": "user", "text": "primeiro turno"},
        {"role": "agent", "agent_id": "agente_a", "text": "resposta do agente"},
        {"role": "user", "text": "segundo turno"},
    ],
}
EXAMPLE = {
    "id": "conv-1-t3-D2", "group_id": "conv-1", "task": "D2", "state": STATE,
    "utterance": "pode ser o segundo",
    "question": "Como o orquestrador deve tratar este turno?", "question_type": "choice",
    "options": {"continuar_agente_ativo": "Continua a tarefa em curso",
                "retomar_sessao:agente_b": "Volta ao assunto do agente_b",
                "iniciar_novo_agente": "Intenção nova",
                "desambiguar": "Não dá para decidir"},
    "gold_label": "continuar_agente_ativo",
}


def words(text):
    return len(text.split())


def test_serialization_is_deterministic_and_ends_with_utterance():
    text = serialize_state(STATE, "pode ser o segundo", 2)
    assert text == serialize_state(STATE, "pode ser o segundo", 2)
    assert text.endswith("Mensagem: pode ser o segundo")
    assert "primeiro turno" not in text and "segundo turno" in text
    assert "Agente ativo: agente_a" in text


def test_zero_turns_has_no_history():
    assert "Turnos anteriores" not in serialize_state(STATE, "x", 0)


def test_fit_drops_oldest_turns_first():
    full = words(serialize_state(STATE, "pode ser o segundo", 3))
    text, info = fit_state(STATE, "pode ser o segundo", 3, full - 1, words)
    assert info["turns_used"] < 3 and info["truncated"]
    assert text.endswith("Mensagem: pode ser o segundo")


def test_fit_cuts_utterance_tail_only_as_last_resort():
    long = "palavra " * 200
    text, info = fit_state(STATE, long, 2, 30, words)
    assert info["turns_used"] == 0 and info["utterance_chars_kept"] < len(long)
    assert words(text) <= 30


def test_to_jev_request_keeps_option_order():
    request, info = to_jev_request(EXAMPLE, "m", n_turns=2)
    q = request["questions"]["D2"]
    assert list(q["criteria"]) == list(EXAMPLE["options"])
    assert q["type"] == "choice" and info["serialization"] == "state-text-v1"


def test_multi_question_example():
    example = dict(EXAMPLE)
    for key in ("question", "question_type", "options", "gold_label"):
        example.pop(key)
    clara = {"true": "sim", "false": "não"}
    example["questions"] = [
        {"name": "pede_x", "question": "Pede X?", "question_type": "noul", "options": clara, "gold_label": "true"},
        {"name": "pede_y", "question": "Pede Y?", "question_type": "noul", "options": clara, "gold_label": "false"},
    ]
    request, _ = to_jev_request(example, "m", n_turns=0)
    assert list(request["questions"]) == ["pede_x", "pede_y"]
