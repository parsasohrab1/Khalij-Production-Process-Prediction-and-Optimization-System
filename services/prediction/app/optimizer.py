"""Evolutionary recommender system — single-variable (backward compatible) and multivariable with safety constraints (phase 4).

Phase 4: simultaneous optimization of feed flow and pressure with Hard Constraints.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .safety_constraints import (
    DEFAULT_BOUNDS,
    ProcessBounds,
    check_hard_constraints,
    clip_to_safe,
    is_feasible,
)

FEED_FLOW_MIN, FEED_FLOW_MAX = 100.0, 500.0
FEED_FLOW_OPTIMAL_CENTER = 300.0
PRESSURE_OPTIMAL_CENTER = 25.0


def estimate_efficiency(reactor_temp_c: float, pressure_bar: float, feed_flow_m3h: float) -> float:
    """Estimated efficiency response surface function based on three process variables."""
    base = (reactor_temp_c - 200) / 150 * 20 + (pressure_bar - 20) / 20 * 10 + 60
    flow_penalty = ((feed_flow_m3h - FEED_FLOW_OPTIMAL_CENTER) / 200) ** 2 * 8
    pressure_penalty = ((pressure_bar - PRESSURE_OPTIMAL_CENTER) / 15) ** 2 * 3
    efficiency = base - flow_penalty - pressure_penalty
    return max(40.0, min(98.0, efficiency))


@dataclass
class Individual:
    feed_flow_m3h: float
    pressure_bar: float


class EvolutionaryRecommender:
    """Backward compatibility: optimizes only the feed flow (original FR-ML-03)."""

    def __init__(
        self,
        population_size: int = 40,
        generations: int = 60,
        mutation_rate: float = 0.15,
        seed: int | None = None,
    ):
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self._rng = random.Random(seed)

    def _random_individual(self) -> float:
        return self._rng.uniform(FEED_FLOW_MIN, FEED_FLOW_MAX)

    def _mutate(self, value: float) -> float:
        if self._rng.random() < self.mutation_rate:
            value += self._rng.gauss(0, 15)
        return max(FEED_FLOW_MIN, min(FEED_FLOW_MAX, value))

    def _crossover(self, a: float, b: float) -> float:
        alpha = self._rng.random()
        return alpha * a + (1 - alpha) * b

    def recommend(self, reactor_temp_c: float, pressure_bar: float, current_feed_flow: float) -> dict:
        population = [self._random_individual() for _ in range(self.population_size)]
        population[0] = current_feed_flow

        best_value, best_score = current_feed_flow, estimate_efficiency(
            reactor_temp_c, pressure_bar, current_feed_flow
        )

        for _ in range(self.generations):
            scored = [(ind, estimate_efficiency(reactor_temp_c, pressure_bar, ind)) for ind in population]
            scored.sort(key=lambda pair: pair[1], reverse=True)
            if scored[0][1] > best_score:
                best_value, best_score = scored[0]
            survivors = [ind for ind, _ in scored[: self.population_size // 2]]
            children = []
            while len(children) < self.population_size - len(survivors):
                parent_a, parent_b = self._rng.sample(survivors, 2)
                children.append(self._mutate(self._crossover(parent_a, parent_b)))
            population = survivors + children

        current_efficiency = estimate_efficiency(reactor_temp_c, pressure_bar, current_feed_flow)
        return {
            "current_value": round(current_feed_flow, 2),
            "recommended_value": round(best_value, 2),
            "expected_efficiency_gain": round(best_score - current_efficiency, 2),
            "algorithm": "evolutionary",
            "variable_name": "feed_flow_m3h",
        }


class MultiVariableEvolutionaryOptimizer:
    """Simultaneous optimization of feed flow and pressure with hard safety constraints (phase 4)."""

    def __init__(
        self,
        population_size: int = 60,
        generations: int = 80,
        mutation_rate: float = 0.2,
        bounds: ProcessBounds | None = None,
        seed: int | None = None,
    ):
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.bounds = bounds or DEFAULT_BOUNDS
        self._rng = random.Random(seed)

    def _random_individual(self, current: Individual) -> Individual:
        p, f = clip_to_safe(
            pressure_bar=self._rng.uniform(self.bounds.pressure_safe_min, self.bounds.pressure_safe_max),
            feed_flow_m3h=self._rng.uniform(self.bounds.feed_flow_safe_min, self.bounds.feed_flow_safe_max),
            current_pressure_bar=current.pressure_bar,
            current_feed_flow=current.feed_flow_m3h,
            bounds=self.bounds,
        )
        return Individual(feed_flow_m3h=f, pressure_bar=p)

    def _mutate(self, ind: Individual, current: Individual) -> Individual:
        f, p = ind.feed_flow_m3h, ind.pressure_bar
        if self._rng.random() < self.mutation_rate:
            f += self._rng.gauss(0, 12)
        if self._rng.random() < self.mutation_rate:
            p += self._rng.gauss(0, 1.2)
        p, f = clip_to_safe(
            pressure_bar=p,
            feed_flow_m3h=f,
            current_pressure_bar=current.pressure_bar,
            current_feed_flow=current.feed_flow_m3h,
            bounds=self.bounds,
        )
        return Individual(feed_flow_m3h=f, pressure_bar=p)

    def _crossover(self, a: Individual, b: Individual) -> Individual:
        alpha = self._rng.random()
        beta = self._rng.random()
        return Individual(
            feed_flow_m3h=alpha * a.feed_flow_m3h + (1 - alpha) * b.feed_flow_m3h,
            pressure_bar=beta * a.pressure_bar + (1 - beta) * b.pressure_bar,
        )

    def _fitness(self, reactor_temp_c: float, ind: Individual, current: Individual) -> float:
        if not is_feasible(
            reactor_temp_c=reactor_temp_c,
            pressure_bar=ind.pressure_bar,
            feed_flow_m3h=ind.feed_flow_m3h,
            current_pressure_bar=current.pressure_bar,
            current_feed_flow=current.feed_flow_m3h,
            bounds=self.bounds,
        ):
            return -1e9  # heavy penalty for violating a hard constraint
        return estimate_efficiency(reactor_temp_c, ind.pressure_bar, ind.feed_flow_m3h)

    def optimize(
        self,
        *,
        reactor_temp_c: float,
        current_pressure_bar: float,
        current_feed_flow: float,
    ) -> dict:
        current = Individual(feed_flow_m3h=current_feed_flow, pressure_bar=current_pressure_bar)
        population = [self._random_individual(current) for _ in range(self.population_size)]
        population[0] = current

        best = current
        best_score = self._fitness(reactor_temp_c, current, current)
        feasible_count = 0

        for _ in range(self.generations):
            scored = [(ind, self._fitness(reactor_temp_c, ind, current)) for ind in population]
            scored.sort(key=lambda pair: pair[1], reverse=True)
            feasible_count = sum(1 for _, s in scored if s > -1e8)

            if scored[0][1] > best_score:
                best, best_score = scored[0]

            survivors = [ind for ind, _ in scored[: self.population_size // 2]]
            children: list[Individual] = []
            while len(children) < self.population_size - len(survivors):
                parent_a, parent_b = self._rng.sample(survivors, 2)
                child = self._mutate(self._crossover(parent_a, parent_b), current)
                children.append(child)
            population = survivors + children

        current_efficiency = estimate_efficiency(reactor_temp_c, current_pressure_bar, current_feed_flow)
        recommended_efficiency = estimate_efficiency(reactor_temp_c, best.pressure_bar, best.feed_flow_m3h)
        violations = check_hard_constraints(
            reactor_temp_c=reactor_temp_c,
            pressure_bar=best.pressure_bar,
            feed_flow_m3h=best.feed_flow_m3h,
            current_pressure_bar=current_pressure_bar,
            current_feed_flow=current_feed_flow,
            bounds=self.bounds,
        )

        return {
            "algorithm": "multivariable_evolutionary",
            "reactor_temp_c": round(reactor_temp_c, 2),
            "current": {
                "feed_flow_m3h": round(current_feed_flow, 2),
                "pressure_bar": round(current_pressure_bar, 2),
                "estimated_efficiency": round(current_efficiency, 2),
            },
            "recommended": {
                "feed_flow_m3h": round(best.feed_flow_m3h, 2),
                "pressure_bar": round(best.pressure_bar, 2),
                "estimated_efficiency": round(recommended_efficiency, 2),
            },
            "expected_efficiency_gain": round(recommended_efficiency - current_efficiency, 2),
            "constraints_satisfied": len(violations) == 0,
            "constraint_violations": [{"name": v.name, "detail": v.detail} for v in violations],
            "feasible_population_ratio": round(feasible_count / max(1, self.population_size), 3),
            # compatibility with the previous single-variable API
            "variable_name": "feed_flow_m3h,pressure_bar",
            "current_value": round(current_feed_flow, 2),
            "recommended_value": round(best.feed_flow_m3h, 2),
        }
