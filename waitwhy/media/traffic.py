"""Ring-road traffic simulation (Intelligent Driver Model + small random fluctuations).

Used so the animation is physically faithful rather than hand-drawn: jams emerge from the model itself.
Setup mirrors Sugiyama et al. 2008 (New J. Phys. 10 033001): 22 cars on a 230 m circuit at ~30 km/h.
Parameters are illustrative (tuned so equilibrium speed is ~30 km/h at that density), NOT fitted to
the experiment's data - visuals are always labelled "simulation".

Two regimes:
* ``jam``    - strongly unstable drivers: a small slowdown grows into full stop-and-go.
* ``smooth`` - milder instability; from ``smoother_on`` one car follows a low-pass-filtered leader speed
              with a larger gap (in the spirit of Stern et al. 2018), which damps the speed variation.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass

import numpy as np

RING_M = 230.0
N_CARS = 22
CAR_M = 4.5


@dataclass(frozen=True)
class Regime:
    v0: float = 11.0       # desired speed m/s
    T: float = 0.4         # time headway s
    a: float = 0.22        # max acceleration m/s^2 (lower = less stable string)
    b: float = 1.5
    s0: float = 1.5
    noise: float = 0.15    # std of random acceleration fluctuations


REGIMES = {"jam": Regime(a=0.22, noise=0.15), "smooth": Regime(a=0.35, noise=0.30)}


@dataclass
class RingSim:
    t: np.ndarray          # (T,)
    x: np.ndarray          # (T, N) arc position in metres [0, RING_M)
    v: np.ndarray          # (T, N) m/s
    acc: np.ndarray        # (T, N) m/s^2
    unwrapped: np.ndarray  # (T, N) monotonically increasing positions

    def at(self, t: float):
        i = int(np.clip(round(t / (self.t[1] - self.t[0])), 0, len(self.t) - 1))
        return self.x[i], self.v[i], self.acc[i]

    def speed_spread_kmh(self, t: float, window: float = 10.0) -> float:
        dt = self.t[1] - self.t[0]
        i1 = int(np.clip(t / dt, 1, len(self.t) - 1))
        i0 = max(0, i1 - int(window / dt))
        return float(self.v[i0:i1].std() * 3.6)


def _idm(v, gap, dv, r: Regime, T=None, a=None, b=None):
    T = r.T if T is None else T
    a = r.a if a is None else a
    b = r.b if b is None else b
    ss = r.s0 + np.maximum(0.0, v * T + v * dv / (2 * np.sqrt(a * b)))
    return a * (1 - (v / r.v0) ** 4 - (ss / np.maximum(gap, 0.1)) ** 2)


@functools.lru_cache(maxsize=8)
def simulate(regime: str = "jam", duration: float = 300.0, seed: int = 3, perturb_car: int = 0,
             perturb_t: float = 10.0, smoother_on: float | None = None, smoother_car: int = 11,
             dt: float = 0.05, record_dt: float = 0.1) -> RingSim:
    r = REGIMES[regime]
    rng = np.random.default_rng(seed)
    x = np.arange(N_CARS) * RING_M / N_CARS
    v = np.full(N_CARS, 30 / 3.6)
    vf = v[0]
    lead = (np.arange(N_CARS) + 1) % N_CARS
    every = int(round(record_dt / dt))
    ts, xs, vs, accs, unw = [], [], [], [], []
    travelled = x.copy()
    for step in range(int(duration / dt) + 1):
        t = step * dt
        gap = (x[lead] - x) % RING_M - CAR_M
        dv = v - v[lead]
        acc = _idm(v, gap, dv, r)
        if perturb_t <= t < perturb_t + 1.0:
            acc[perturb_car] -= 1.5
        acc = acc + rng.normal(0, r.noise, N_CARS)
        if smoother_on is not None:
            i = smoother_car
            vf += (v[lead[i]] - vf) * dt / 30.0
            if t >= smoother_on:
                a_ctrl = 0.3 * (vf - v[i]) + 0.02 * (gap[i] - (2.0 + 1.0 * v[i]))
                a_safe = _idm(v[i:i + 1], gap[i:i + 1], dv[i:i + 1], r, T=0.6, a=1.0, b=2.0)[0]
                acc[i] = float(np.clip(min(a_ctrl, a_safe), -3.0, 1.0))
        v = np.clip(v + acc * dt, 0.0, None)
        x = (x + v * dt) % RING_M
        travelled = travelled + v * dt
        if step % every == 0:
            ts.append(t)
            xs.append(x.copy())
            vs.append(v.copy())
            accs.append(acc.copy())
            unw.append(travelled.copy())
    return RingSim(np.array(ts), np.array(xs), np.array(vs), np.array(accs), np.array(unw))


def jam_drift_kmh(sim: RingSim, t0: float = 150.0) -> float:
    """Velocity of the slowest-car location (the jam) - negative = moving backwards."""
    mask = sim.t >= t0
    pos = np.array([sim.x[i][np.argmin(sim.v[i])] for i in np.where(mask)[0]])
    ang = np.unwrap(pos / RING_M * 2 * np.pi) * RING_M / (2 * np.pi)
    slope = np.polyfit(sim.t[mask], ang, 1)[0]
    return float(slope * 3.6)
