"""Input data Drift detection to trigger Re-training (phase 3).

The Population Stability Index (PSI) is used on the reactor temperature distribution.
If PSI exceeds the threshold, the data distribution has changed relative to the training baseline and
the model must be retrained.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def population_stability_index(
    baseline: np.ndarray,
    current: np.ndarray,
    n_bins: int = 10,
    eps: float = 1e-6,
) -> float:
    """Compute PSI between two one-dimensional distributions."""
    baseline = np.asarray(baseline, dtype=float)
    current = np.asarray(current, dtype=float)
    if len(baseline) < n_bins or len(current) < n_bins:
        return 0.0

    quantiles = np.linspace(0, 100, n_bins + 1)
    breakpoints = np.unique(np.percentile(baseline, quantiles))
    if len(breakpoints) < 2:
        return 0.0

    baseline_counts = np.histogram(baseline, bins=breakpoints)[0].astype(float)
    current_counts = np.histogram(current, bins=breakpoints)[0].astype(float)

    baseline_pct = baseline_counts / max(baseline_counts.sum(), eps)
    current_pct = current_counts / max(current_counts.sum(), eps)

    baseline_pct = np.clip(baseline_pct, eps, None)
    current_pct = np.clip(current_pct, eps, None)

    return float(np.sum((current_pct - baseline_pct) * np.log(current_pct / baseline_pct)))


class DriftDetector:
    """Keeps the training baseline and detects drift on the recent window."""

    def __init__(self, psi_threshold: float = 0.25, min_samples: int = 100):
        self.psi_threshold = psi_threshold
        self.min_samples = min_samples
        self._baseline: np.ndarray | None = None

    def set_baseline(self, series: list[float] | np.ndarray) -> None:
        self._baseline = np.asarray(series, dtype=float)
        logger.info("Drift baseline set with %d samples.", len(self._baseline))

    @property
    def has_baseline(self) -> bool:
        return self._baseline is not None and len(self._baseline) >= self.min_samples

    def check(self, current_series: list[float] | np.ndarray) -> dict:
        current = np.asarray(current_series, dtype=float)
        if not self.has_baseline or len(current) < self.min_samples:
            return {"drift_detected": False, "psi": 0.0, "reason": "insufficient_samples"}

        psi = population_stability_index(self._baseline, current)
        detected = psi >= self.psi_threshold
        if detected:
            logger.warning("Drift detected: PSI=%.4f (threshold=%.2f)", psi, self.psi_threshold)
        return {
            "drift_detected": detected,
            "psi": round(psi, 4),
            "threshold": self.psi_threshold,
            "reason": "psi_exceeded" if detected else "stable",
        }
