"""
Test file for NHL Faceoff ELO System
"""


def calculate_expected_score(rating_a: float, rating_b: float) -> float:
    """
    Calculate expected score for player A against player B.
    
    Args:
        rating_a: ELO rating of player A
        rating_b: ELO rating of player B
    
    Returns:
        Expected score (probability of winning) for player A
    """
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(rating: float, expected: float, actual: float, k: float = 32) -> float:
    """
    Update ELO rating based on game result.
    
    Args:
        rating: Current ELO rating
        expected: Expected score
        actual: Actual result (1 for win, 0 for loss)
        k: K-factor (sensitivity of rating changes)
    
    Returns:
        New ELO rating
    """
    return rating + k * (actual - expected)


if __name__ == "__main__":
    # Simple test
    player_a_rating = 1500
    player_b_rating = 1500
    
    print("NHL Faceoff ELO System - Test")
    print("=" * 40)
    print(f"Player A initial rating: {player_a_rating}")
    print(f"Player B initial rating: {player_b_rating}")
    
    expected_a = calculate_expected_score(player_a_rating, player_b_rating)
    print(f"\nExpected score for A: {expected_a:.3f}")
    
    # Simulate A winning the faceoff
    new_rating_a = update_elo(player_a_rating, expected_a, 1)
    new_rating_b = update_elo(player_b_rating, 1 - expected_a, 0)
    
    print(f"\nAfter A wins faceoff:")
    print(f"Player A new rating: {new_rating_a:.1f}")
    print(f"Player B new rating: {new_rating_b:.1f}")
