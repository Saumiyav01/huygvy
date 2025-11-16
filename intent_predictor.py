# intent_predictor.py
from typing import Dict, Tuple

class IntentPredictor:
    """
    Rule-based intent predictor. Easy to read and replace with ML later.
    Outputs: (intent_label, probabilities_dict, confidence)
    Intents: push, conserve, prepare_pit, bluff
    """

    INTENTS = ["push", "conserve", "prepare_pit", "bluff"]

    def __init__(self):
        pass

    def predict(self, features: Dict) -> Tuple[str, Dict, float]:
        # if no features yet, return neutral 'conserve'
        if not features:
            probs = {i: 1.0/len(self.INTENTS) for i in self.INTENTS}
            return "conserve", probs, 1.0/len(self.INTENTS)

        spd_mean = features.get("speed_mean", 0.0)
        spd_std  = features.get("speed_std", 0.0)
        delta_speed = features.get("delta_speed", 0.0)
        throttle = features.get("throttle_mean", 0.0)
        brake = features.get("brake_mean", 0.0)
        lapprog_slope = features.get("lapprog_slope", 0.0)
        tyre_temp = features.get("tyre_temp_mean", 0.0)

        scores = {i: 0.0 for i in self.INTENTS}

        # push: high speed, positive delta_speed, decent throttle
        if spd_mean > 35 and delta_speed > 0.5 and throttle > 40:
            scores["push"] += 2.0
        if spd_std > 3.0:
            scores["push"] += 0.5

        # prepare_pit: high tyre temp OR heavy braking + slowing lap progress
        if tyre_temp > 80 and brake > 10:
            scores["prepare_pit"] += 2.0
        if brake > 20 and lapprog_slope < 0:
            scores["prepare_pit"] += 1.0

        # conserve: low speed, low throttle, low variance
        if spd_mean < 25 and throttle < 30 and spd_std < 2.0:
            scores["conserve"] += 2.0
        if abs(lapprog_slope) < 0.001:
            scores["conserve"] += 0.5

        # bluff: high variance + odd delta speed with little braking
        if spd_std > 6.0 and abs(delta_speed) > 3.0 and brake < 5:
            scores["bluff"] += 1.5

        # tiny smoothing to avoid zero-sum
        for k in scores:
            scores[k] += 0.01

        total = sum(scores.values())
        probs = {k: float(v/total) for k,v in scores.items()}
        intent = max(probs, key=probs.get)
        confidence = float(probs[intent])
        return intent, probs, confidence
