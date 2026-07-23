"""سیستم توصیه‌گر مبتنی بر الگوریتم تکاملی برای دبی خوراک بهینه (FR-ML-03).

یک الگوریتم ژنتیک ساده (بدون وابستگی سنگین خارجی) که با توجه به دما و فشار
فعلی راکتور، مقدار دبی خوراک ورودی را برای بیشینه‌سازی راندمان تخمینی جست‌وجو می‌کند.
"""
from __future__ import annotations

import random

FEED_FLOW_MIN, FEED_FLOW_MAX = 100.0, 500.0
FEED_FLOW_OPTIMAL_CENTER = 300.0  # نقطه مرکزی محدوده کارایی بهینه راکتور


def estimate_efficiency(reactor_temp_c: float, pressure_bar: float, feed_flow_m3h: float) -> float:
    """تابع سطح پاسخ (Response Surface) تخمینی راندمان بر اساس سه متغیر فرایندی.

    این رابطه بر پایه فرمول efficiency_target در اسکریپت تولید داده سنتتیک است
    و یک جمله جزایی برای انحراف دبی خوراک از محدوده بهینه به آن افزوده شده تا
    فضای جست‌وجوی الگوریتم تکاملی معنادار باشد.
    """
    base = (reactor_temp_c - 200) / 150 * 20 + (pressure_bar - 20) / 20 * 10 + 60
    flow_penalty = ((feed_flow_m3h - FEED_FLOW_OPTIMAL_CENTER) / 200) ** 2 * 8
    efficiency = base - flow_penalty
    return max(40.0, min(98.0, efficiency))


class EvolutionaryRecommender:
    """الگوریتم ژنتیک ساده: جمعیت -> ارزیابی -> انتخاب -> تلاقی -> جهش."""

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
        population[0] = current_feed_flow  # حفظ نقطه شروع فعلی برای همگرایی پایدارتر

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
                child = self._mutate(self._crossover(parent_a, parent_b))
                children.append(child)
            population = survivors + children

        current_efficiency = estimate_efficiency(reactor_temp_c, pressure_bar, current_feed_flow)
        return {
            "current_value": round(current_feed_flow, 2),
            "recommended_value": round(best_value, 2),
            "expected_efficiency_gain": round(best_score - current_efficiency, 2),
            "algorithm": "evolutionary",
        }
