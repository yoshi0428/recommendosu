from collections import defaultdict
from typing import Dict, List, Set

import requests
import sqlite3
from tqdm import tqdm

from backend.recommender.osu_api_client import OsuAPIClient

MODE = "osu"
RANKINGS_DB = '../rankings.db'

# How many scores to use for each player's interaction history.
TOP_SCORE_LIMIT = 100
RECENT_SCORE_LIMIT = 50

# ============================================================
# Player Retrieval
# ============================================================

def get_player(
    api: OsuAPIClient,
    player_id: int,
) -> dict:
    """
    Get the target player's information.
    """

    return api.get(
        f"/users/{player_id}/{MODE}"
    )


def get_players(
    api: OsuAPIClient,
    current_player_id: int,
    k: int,
    db_path: str = RANKINGS_DB,
) -> List[dict]:
    """
    Fetch the target player and their nearest ranked players.

    The local SQLite ranking database is used instead of the
    osu! ranking endpoint.

    Returned players are sorted by ascending global rank.
    """

    # --------------------------------------------------------
    # Get the target player's current information
    # --------------------------------------------------------

    current_player = get_player(
        api,
        current_player_id,
    )

    statistics = current_player.get(
        "statistics"
    )

    if not statistics:
        raise RuntimeError(
            f"Player {current_player_id} "
            f"has no ranking statistics."
        )

    current_rank = statistics.get(
        "global_rank"
    )

    if current_rank is None:
        raise RuntimeError(
            f"Player {current_player_id} "
            f"is not globally ranked."
        )

    print(
        f"Target player rank: #{current_rank}"
    )

    # --------------------------------------------------------
    # Determine rank window
    # --------------------------------------------------------

    if current_rank == 1:

        start_rank = 2
        end_rank = 1 + k

    elif current_rank > k:

        start_rank = current_rank - k
        end_rank = current_rank - 1

    else:

        above_count = current_rank - 1
        remaining = k - above_count

        start_rank = 1
        end_rank = current_rank + remaining

    print(
        f"Fetching ranking window: "
        f"#{start_rank} to #{end_rank}"
    )

    # --------------------------------------------------------
    # Query SQLite
    # --------------------------------------------------------

    with sqlite3.connect(db_path) as conn:

        rows = conn.execute(
            """
            SELECT
                rank,
                player_id
            FROM rankings
            WHERE rank BETWEEN ? AND ?
            ORDER BY rank
            """,
            (
                start_rank,
                end_rank,
            ),
        ).fetchall()

    # --------------------------------------------------------
    # Convert database rows into expected structure
    # --------------------------------------------------------

    players = []

    for rank, player_id in rows:

        players.append({
            "player_id": player_id,
            "rank": rank,
            "username": None,
        })

    # --------------------------------------------------------
    # Add target player
    # --------------------------------------------------------

    if not any(
        p["player_id"] == current_player_id
        for p in players
    ):

        players.append({
            "player_id": current_player_id,
            "rank": current_rank,
            "username": current_player.get(
                "username"
            ),
        })

    players.sort(
        key=lambda x: x["rank"]
    )

    return players


# ============================================================
# Comparison Player Selection
# ============================================================

def get_comparison_players(
    players,
    current_player_id,
    k,
):
    """
    players:
        Rank-sorted list of player dictionaries.

    current_player_id:
        Target player's ID.

    k:
        Number of comparison players.

    Rules:

    - Rank #1:
        Take k players below.

    - If rank position >= k:
        Take k players above.

    - If there are fewer than k players above:
        Take all available players above,
        then fill the remaining slots below.
    """

    current_idx = next(
        i
        for i, p in enumerate(players)
        if p["player_id"] == current_player_id
    )

    # --------------------------------------------------------
    # Rank #1
    # --------------------------------------------------------

    if current_idx == 0:

        return players[
            1:1 + k
        ]

    # --------------------------------------------------------
    # k or more players above
    # --------------------------------------------------------

    if current_idx >= k:

        return players[
            current_idx - k:
            current_idx
        ]

    # --------------------------------------------------------
    # Fewer than k players above
    # --------------------------------------------------------

    above = players[
        :current_idx
    ]

    remaining = (
        k - len(above)
    )

    below = players[
        current_idx + 1:
        current_idx + 1 + remaining
    ]

    return above + below


# ============================================================
# Player Map History
# ============================================================

def get_user_scores(
    api: OsuAPIClient,
    player_id: int,
    score_type: str,
    limit: int,
) -> list:
    """
    Fetch a player's scores.

    score_type:
        "best" or "recent"
    """

    return api.get(
        f"/users/{player_id}/scores/{score_type}",
        params={
            "mode": MODE,
            "limit": limit,
            "include_fails": 0,
        },
    )


def extract_beatmap_ids(
    scores: list,
) -> Set[int]:
    """
    Extract unique beatmap IDs from score objects.
    """

    return {
        score["beatmap_id"]
        for score in scores
        if score.get("beatmap_id") is not None
    }


def get_player_maps(
    api: OsuAPIClient,
    player_id: int,
) -> Set[int]:
    """
    Build the player's map interaction set.

    We combine:

    - top plays
    - recent plays

    The result is a set of unique beatmap IDs.
    """

    top_scores = get_user_scores(
        api=api,
        player_id=player_id,
        score_type="best",
        limit=TOP_SCORE_LIMIT,
    )

    recent_scores = get_user_scores(
        api=api,
        player_id=player_id,
        score_type="recent",
        limit=RECENT_SCORE_LIMIT,
    )

    top_maps = extract_beatmap_ids(
        top_scores
    )

    recent_maps = extract_beatmap_ids(
        recent_scores
    )

    return top_maps | recent_maps


def build_maps_played(
    api: OsuAPIClient,
    player_ids: List[int],
) -> Dict[int, Set[int]]:
    """
    Fetch interaction histories for all players.

    maps_played:

    {
        player_id: {
            beatmap_id_1,
            beatmap_id_2,
            ...
        }
    }
    """

    maps_played = {}

    for player_id in tqdm(
        player_ids,
        desc="Fetching player map histories",
    ):

        try:

            maps_played[player_id] = (
                get_player_maps(
                    api,
                    player_id,
                )
            )

        except requests.HTTPError as e:

            print(
                f"\nSkipping player "
                f"{player_id}: {e}"
            )

            maps_played[player_id] = set()

        except Exception as e:

            print(
                f"\nUnexpected error for player "
                f"{player_id}: {e}"
            )

            maps_played[player_id] = set()

    return maps_played


# ============================================================
# Similarity
# ============================================================

def jaccard_similarity(
    maps_a,
    maps_b,
):
    """
    Calculate similarity based on
    beatmap-play overlap.
    """

    intersection = len(
        maps_a & maps_b
    )

    union = len(
        maps_a | maps_b
    )

    if union == 0:
        return 0.0

    return intersection / union


# ============================================================
# Candidate Generation
# ============================================================

def generate_candidates(
    user_maps,
    similar_players,
    maps_played,
):
    """
    Generate candidate beatmaps.

    Each candidate receives the sum of
    the similarity scores of players
    who have played it.
    """

    candidate_scores = defaultdict(float)

    candidate_sources = defaultdict(list)

    for player in similar_players:

        player_id = player["player_id"]

        similarity = player["similarity"]

        # No overlap means this player provides
        # no collaborative signal.
        if similarity <= 0:
            continue

        for map_id in maps_played[player_id]:

            # Never recommend maps already played
            # by the target user.
            if map_id in user_maps:
                continue

            candidate_scores[map_id] += similarity

            candidate_sources[map_id].append({
                "player_id": player_id,
                "rank": player["rank"],
                "similarity": similarity,
            })

    return candidate_scores, candidate_sources


# ============================================================
# Main
# ============================================================

def main():

    # --------------------------------------------------------
    # Configuration
    # --------------------------------------------------------

    current_player_id = 10961031
    k = 10
    page_size = 50

    api = OsuAPIClient()
    # --------------------------------------------------------
    # Fetch target + comparison ranking window
    # --------------------------------------------------------

    players = get_players(
        api=api,
        current_player_id=current_player_id,
        k=k,
        page_size=page_size
    )

    print("\nPlayers in rank window:")

    for player in players:

        marker = ""

        if (
            player["player_id"]
            == current_player_id
        ):
            marker = " <-- TARGET"

        print(
            f"#{player['rank']:>7} "
            f"{player['username']} "
            f"({player['player_id']})"
            f"{marker}"
        )

    exit()

    # --------------------------------------------------------
    # Select comparison players
    # --------------------------------------------------------

    comparison_players = (
        get_comparison_players(
            players=players,
            current_player_id=current_player_id,
            k=k,
        )
    )

    print(
        "\nComparison players:"
    )

    for player in comparison_players:

        print(
            f"#{player['rank']:>7} "
            f"{player['username']} "
            f"({player['player_id']})"
        )

    exit()

    # --------------------------------------------------------
    # Fetch map histories
    #
    # Include target player plus all comparison players.
    # --------------------------------------------------------

    all_player_ids = [
        current_player_id
    ] + [
        player["player_id"]
        for player in comparison_players
    ]

    print(all_player_ids)

    maps_played = build_maps_played(
        api=api,
        player_ids=all_player_ids,
    )

    # --------------------------------------------------------
    # User history
    # --------------------------------------------------------

    user_maps = maps_played[current_player_id]

    print(
        f"\nTarget player has "
        f"{len(user_maps)} unique maps "
        f"in the sampled history."
    )

    exit()

    # --------------------------------------------------------
    # Similar-player comparison
    # --------------------------------------------------------

    similar_players = []

    for player in comparison_players:

        player_id = player["player_id"]

        player_maps = maps_played[player_id]

        similarity = jaccard_similarity(
            user_maps,
            player_maps,
        )

        similar_players.append({
            "player_id": player_id,
            "username": player["username"],
            "rank": player["rank"],
            "similarity": similarity,
            "shared_maps": len(
                user_maps & player_maps
            ),
            "total_maps": len(
                player_maps
            ),
        })

    similar_players.sort(
        key=lambda x: x["similarity"],
        reverse=True,
    )

    # --------------------------------------------------------
    # Print similar players
    # --------------------------------------------------------

    print("\nSimilar players:")
    print("-" * 80)

    for player in similar_players:

        print(
            f"#{player['rank']:>7} "
            f"{player['username']:<20} "
            f"similarity={player['similarity']:.4f} "
            f"shared={player['shared_maps']}"
        )

    # --------------------------------------------------------
    # Candidate generation
    # --------------------------------------------------------

    (
        candidate_scores,
        candidate_sources,
    ) = generate_candidates(
        user_maps=user_maps,
        similar_players=similar_players,
        maps_played=maps_played,
    )

    # --------------------------------------------------------
    # Sort candidates
    # --------------------------------------------------------

    ranked_candidates = sorted(
        candidate_scores.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------

    print(
        f"\nGenerated "
        f"{len(ranked_candidates)} "
        f"candidate beatmaps."
    )

    print("\nTop 50 candidates:")
    print("-" * 80)

    for rank, (
        map_id,
        score,
    ) in enumerate(
        ranked_candidates[:50],
        start=1,
    ):

        sources = candidate_sources[
            map_id
        ]

        print(
            f"{rank:>3}. "
            f"beatmap_id={map_id:<10} "
            f"score={score:.4f} "
            f"similar_players={len(sources)}"
        )


if __name__ == "__main__":
    main()