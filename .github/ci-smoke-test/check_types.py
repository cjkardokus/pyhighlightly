"""Throwaway script for CI's build-and-install job.

This is only ever type-checked (by ``mypy``), never executed. Its only job
is to confirm that pyhighlightly ships type information a real downstream
consumer's type checker can actually see once the package is installed from
its built wheel -- as opposed to checked against this repo's own source
tree, which is what every other CI job does and which can't detect a
packaging problem like a missing ``py.typed`` marker.

See the "Confirm type information ships with the wheel" step in
.github/workflows/ci.yml for how this is invoked.
"""

from pyhighlightly import NFLClient


def get_first_team_name(client: NFLClient) -> str:
    teams = client.get_teams()
    return teams[0].displayName
