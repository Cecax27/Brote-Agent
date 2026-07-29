import random
from typing import TypedDict


class StatusVariant(TypedDict):
    text: str
    humor: bool


STATUS_GROUPS: dict[str, list[StatusVariant]] = {
    "loading_memory": [
        {"text": "Recordando nuestra última charla…", "humor": False},
        {"text": "Recuperando el hilo de la conversación…", "humor": False},
        {"text": "Repasando lo que hablamos…", "humor": False},
    ],
    "reading_garden": [
        {"text": "Mirando tu jardín…", "humor": False},
        {"text": "Revisando mis apuntes de tus plantas…", "humor": False},
        {"text": "Buscando en tu jardín…", "humor": False},
        {"text": "Consultando el estado de tus plantas…", "humor": False},
        {"text": "Conectando con la sabiduría vegetal…", "humor": True},
        {"text": "Las hojas me están contando…", "humor": True},
    ],
    "analyzing_photo": [
        {"text": "Analizando la foto…", "humor": False},
        {"text": "Examinando la imagen…", "humor": False},
        {"text": "Observando cada detalle…", "humor": False},
        {"text": "Acerco la lupa virtual…", "humor": True},
        {"text": "Mis ojos digitales están trabajando…", "humor": True},
    ],
    "thinking": [
        {"text": "Pensando…", "humor": False},
        {"text": "Déjame pensar…", "humor": False},
        {"text": "Preparando una respuesta…", "humor": False},
        {"text": "Elaborando una respuesta…", "humor": False},
        {"text": "Déjame consultar con las hojas…", "humor": True},
    ],
    "writing_memory": [
        {"text": "Guardando esto para no olvidarlo…", "humor": False},
        {"text": "Anotando en el diario…", "humor": False},
    ],
}


def pick_status(step_key: str, *, include_humor: bool = True) -> str:
    variants = STATUS_GROUPS.get(step_key, [{"text": "Procesando…", "humor": False}])
    pool = [v["text"] for v in variants if include_humor or not v["humor"]]
    if not pool:
        pool = [v["text"] for v in variants if not v["humor"]]
    return random.choice(pool)
