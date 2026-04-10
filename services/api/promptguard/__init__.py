"""
promptguard — layered prompt screening framework.

Layers are applied in order; the first BLOCK result short-circuits.
Each layer is independent and testable in isolation.

Usage::

    from promptguard import ScreeningPipeline
    from promptguard.layers.obfuscation import ObfuscationLayer

    pipeline = ScreeningPipeline([ObfuscationLayer()])
    result = pipeline.screen("some user text")
    if result.blocked:
        ...
"""
from promptguard.pipeline import ScreeningPipeline

__all__ = ["ScreeningPipeline"]
