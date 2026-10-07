"""Cliente mínimo do OCI Generative AI (chat on-demand) para geração e anotação de dados.

Autenticação: resource principal (jobs/notebooks), instance principal (VM, DMB_OCI_AUTH=instance_principal)
ou a chave de API em .secrets/ (máquina local).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

GENAI_REGION = os.environ.get("DMB_GENAI_REGION", "us-chicago-1")
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=None)
def _client_and_compartment():
    import oci

    endpoint = f"https://inference.generativeai.{GENAI_REGION}.oci.oraclecloud.com"
    retry = oci.retry.DEFAULT_RETRY_STRATEGY
    if os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"):
        signer = oci.auth.signers.get_resource_principals_signer()
        client = oci.generative_ai_inference.GenerativeAiInferenceClient(
            {}, signer=signer, service_endpoint=endpoint, retry_strategy=retry, timeout=(10, 300))
    elif os.environ.get("DMB_OCI_AUTH") == "instance_principal":
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        client = oci.generative_ai_inference.GenerativeAiInferenceClient(
            {}, signer=signer, service_endpoint=endpoint, retry_strategy=retry, timeout=(10, 300))
    else:
        sys.path.insert(0, str(ROOT / "infra" / "oci"))
        from session import load_config
        client = oci.generative_ai_inference.GenerativeAiInferenceClient(
            load_config(region=GENAI_REGION), service_endpoint=endpoint, retry_strategy=retry, timeout=(10, 300))
    compartment = os.environ.get("DMB_COMPARTMENT_OCID") or os.environ.get("JOB_COMPARTMENT_OCID")
    if not compartment:
        raise RuntimeError("defina DMB_COMPARTMENT_OCID")
    return client, compartment


def chat(model: str, system: str, user: str, temperature: float = 0.7, max_tokens: int = 4000,
         attempts: int = 4) -> str:
    import oci
    from oci.generative_ai_inference import models as m

    client, compartment = _client_and_compartment()
    if model.startswith("cohere."):
        request = m.CohereChatRequest(preamble_override=system, message=user, temperature=temperature,
                                      max_tokens=max_tokens)
    else:
        msgs = [m.SystemMessage(content=[m.TextContent(text=system)]),
                m.UserMessage(content=[m.TextContent(text=user)])]
        kwargs = {"messages": msgs, "temperature": temperature}
        # modelos de raciocínio da OpenAI só aceitam max_completion_tokens e temperatura padrão
        if model.startswith("openai.gpt-5") or model.startswith("openai.o"):
            kwargs.pop("temperature")
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
        request = m.GenericChatRequest(**kwargs)
    details = m.ChatDetails(compartment_id=compartment, serving_mode=m.OnDemandServingMode(model_id=model),
                            chat_request=request)
    for attempt in range(attempts):
        try:
            resp = client.chat(details).data.chat_response
            if model.startswith("cohere."):
                return resp.text
            return "".join(c.text for c in resp.choices[0].message.content if getattr(c, "text", None))
        except oci.exceptions.ServiceError as error:
            if error.status in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(5 * 2 ** attempt)
                continue
            raise


def extract_json(text: str):
    """Primeiro objeto ou lista JSON do texto (tolera cercas ```json)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"resposta sem JSON válido: {text[:200]!r}")
