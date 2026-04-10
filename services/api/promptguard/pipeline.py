"""
promptguard.pipeline
────────────────────
Runs a sequence of layers in order; short-circuits on the first BLOCK.
"""
from __future__ import annotations
from typing import Sequence

from promptguard.layers.base import BaseLayer, LayerResult


class ScreeningPipeline:
    """
    Runs *layers* in sequence and returns the first blocking result.

    Parameters
    ----------
    layers: ordered list of BaseLayer instances
    """

    def __init__(self, layers: Sequence[BaseLayer]) -> None:
        self._layers = list(layers)

    def screen(self, text: str) -> LayerResult:
        """
        Screen *text* through all layers in order.
        Returns the first blocking LayerResult, or LayerResult.allow() if all pass.
        """
        for layer in self._layers:
            result = layer.screen(text)
            if result.blocked:
                return result
        return LayerResult.allow()
