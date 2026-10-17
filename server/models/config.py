"""Explicit offline/live selection; no automatic fallback after provider errors."""
from dataclasses import dataclass
import os

from .fixtures import FixtureModels


@dataclass
class Models:
    extractor: object
    capture: object
    embedder: object
    answerer: object
    mode: str


def build_models(mode=None):
    mode = mode or os.environ.get("SYNAPSE_MODEL_MODE", "fixture")
    if mode == "fixture":
        model = FixtureModels()
        return Models(model, model, model, model, mode)
    if mode == "live":
        from .gemini import GeminiExtractor
        from .capture import GeminiCapture
        from .rag import GeminiAnswerer, GeminiEmbedder
        return Models(GeminiExtractor(), GeminiCapture(), GeminiEmbedder(), GeminiAnswerer(), mode)
    raise ValueError("SYNAPSE_MODEL_MODE must be fixture or live")
