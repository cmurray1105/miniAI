from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field


EVENTS = [
    ("00:40", "A honeymooning pair of lunar diplomats reports that their suite has lost gravity.",
     [("Reroute power from the ballroom", {"power": -18, "mood": 8, "credits": -40}),
      ("Send maintenance drones", {"power": -6, "mood": 3, "staff": -8}),
      ("Offer the honeymoon suite an upgrade", {"credits": -90, "mood": 12})]),
    ("02:15", "The casino's nebula projector is overheating and drawing more power every minute.",
     [("Shut it down before it fails", {"power": 12, "mood": -6}),
      ("Throttle it and monitor the heat", {"power": 5, "mood": 1, "risk": 8}),
      ("Keep the show running", {"credits": 55, "risk": 18})]),
    ("04:50", "A cargo shuttle arrived early with a crate that is making polite knocking sounds.",
     [("Quarantine it in cargo", {"staff": -5, "risk": -8}),
      ("Call the xenobiologist on duty", {"credits": -35, "risk": -14}),
      ("Open it in the lobby", {"mood": 10, "risk": 25})]),
    ("06:30", "The breakfast synthesizer begins producing identical croissants at an alarming rate.",
     [("Disable the synthesizer", {"mood": -5, "power": 7}),
      ("Serve croissants until supplies run out", {"mood": 7, "credits": 20, "risk": 6}),
      ("Ask engineering to patch it", {"staff": -10, "risk": -5})]),
]


@dataclass
class Shift:
    id: str
    event: int = 0
    power: int = 72
    mood: int = 64
    staff: int = 76
    credits: int = 180
    risk: int = 12
    history: list[str] = field(default_factory=list)


_shifts: dict[str, Shift] = {}


def _view(shift: Shift) -> dict:
    done = shift.event >= len(EVENTS)
    payload = {"shift_id": shift.id, "state": asdict(shift), "complete": done}
    if done:
        score = shift.mood + shift.staff + shift.power - shift.risk + shift.credits // 10
        payload["report"] = f"Shift complete. Your station score is {score}. " + (
            "The hotel survived with style." if score >= 130 else "You kept the lights on. Barely."
        )
    else:
        time, problem, choices = EVENTS[shift.event]
        payload["incident"] = {"time": time, "problem": problem,
                               "choices": [{"id": i, "label": choice[0]} for i, choice in enumerate(choices)]}
    return payload


def start() -> dict:
    shift = Shift(id=str(uuid.uuid4()))
    _shifts[shift.id] = shift
    return _view(shift)


def choose(shift_id: str, choice_id: int) -> dict:
    shift = _shifts.get(shift_id)
    if not shift or shift.event >= len(EVENTS):
        raise KeyError("shift not found or already complete")
    _, _, choices = EVENTS[shift.event]
    if choice_id not in range(len(choices)):
        raise ValueError("invalid choice")
    label, effects = choices[choice_id]
    for key, amount in effects.items():
        setattr(shift, key, max(0, min(100 if key != "credits" else 999, getattr(shift, key) + amount)))
    shift.history.append(label)
    shift.event += 1
    return _view(shift)
