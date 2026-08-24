"""Match Kickbase players/teams to Ligainsider entities by normalized names."""

import re
import unicodedata

# Kickbase short team names that normalized containment can't resolve.
TEAM_ALIASES = {
    "gladbach": "borussia monchengladbach",
    "m gladbach": "borussia monchengladbach",
    "frankfurt": "eintracht frankfurt",
    "koln": "1 fc koln",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def map_teams(kickbase_teams: list[dict], ligainsider_teams: list[dict]) -> dict:
    """Kickbase tid -> ligainsider team name, via name containment."""
    mapping = {}
    for kb in kickbase_teams:
        kb_name = normalize(kb["tn"])
        kb_name = TEAM_ALIASES.get(kb_name, kb_name)
        for li in ligainsider_teams:
            li_name = normalize(li["name"])
            if kb_name in li_name or li_name in kb_name:
                mapping[kb["tid"]] = li["name"]
                break
    return mapping


def match_player(kickbase_name: str, candidates: list[dict]) -> dict | None:
    """Find the Ligainsider entry whose URL slug contains the Kickbase name.

    Kickbase uses last names ("Anton", "El Mala"); Ligainsider slugs hold the
    full name ("/waldemar-anton_5837/"). Candidates should already be scoped
    to one team, so token containment is unambiguous in practice.
    """
    tokens = normalize(kickbase_name).split()
    if not tokens:
        return None
    for cand in candidates:
        slug = normalize((cand.get("player_url") or "").split("_")[0])
        slug_tokens = slug.split()
        if all(t in slug_tokens for t in tokens):
            return cand
    return None
