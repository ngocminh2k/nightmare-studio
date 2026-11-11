"""One-off live check of the repaired SystemOne director client."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.providers import ProviderSettings
from app.systemone import RouterSystemOneClient, evaluate_scene_director

client = RouterSystemOneClient(ProviderSettings.from_environment())
print("model:", client.model)
print("candidates:", client._candidate_models)

for narration, nxt in [
    ("Victor Kane steps into the drowned manor, notebook open.", "The water laps at his boots."),
    ("The drowned manor sinks into the fog, its windows dark.", "A bell tolls somewhere below."),
    ("A rusted iron key rests on wet stone, half buried in silt.", ""),
]:
    dur, shot, trans = evaluate_scene_director(client, narration, nxt)
    print(f"-> duration={dur} shot_type={shot} transition={trans}  | {narration[:50]}")

print("_remote_disabled:", client._remote_disabled)
print("parked:", client._parked_until)
