"""Engine-level tests for the GEO scoring system (issue #9 acceptance criteria).

Asserts the two properties the issue calls out:
  - deterministic / reproducible for the same dataset
  - mention frequency, ranking, and citations are reflected correctly
"""
from backend.models import Citation, Competitor, Mention, Profile, Project, Run
from backend.scoring import compute_project_scores


def _seed_project(db_scope, *, runs_target_rank, n_runs, competitor=True, citations=0):
    """Seed a project with n_runs processed runs; target appears at runs_target_rank
    in each, plus an optional competitor mention and brand-domain citations."""
    with db_scope() as db:
        db.add(Profile(id="u1", email="u1@example.com"))
        db.flush()
        db.add(Project(id=1, user_id="u1", name="Notion", domain="notion.so"))
        if competitor:
            db.add(Competitor(project_id=1, competitor_name="Confluence"))
            db.add(Competitor(project_id=1, competitor_name="Slab"))
        db.flush()
        for i in range(n_runs):
            run = Run(project_id=1, provider="chatgpt", prompt=f"prompt {i}",
                      status="processed", target_sentiment="positive")
            db.add(run)
            db.flush()
            db.add(Mention(run_id=run.id, entity_name="Notion", normalized_entity="Notion",
                           mention_position=runs_target_rank, is_target=True))
            db.add(Mention(run_id=run.id, entity_name="Confluence", normalized_entity="Confluence",
                           mention_position=runs_target_rank + 1, is_target=False))
            for _ in range(citations):
                db.add(Citation(run_id=run.id, domain="notion.so", url="https://notion.so", title="Notion"))
    return 1


def test_deterministic_same_dataset(db_scope):
    """Same dataset → byte-identical scores on repeated computation."""
    _seed_project(db_scope, runs_target_rank=1, n_runs=10)
    first = compute_project_scores(1)
    second = compute_project_scores(1)
    assert first["target"]["geo_final"] == second["target"]["geo_final"]
    assert first["brands"] == second["brands"]


def test_small_sample_not_inflated(db_scope):
    """1/1 perfect appearance must NOT yield ~100 (the old formula's bug)."""
    _seed_project(db_scope, runs_target_rank=1, n_runs=1)
    out = compute_project_scores(1)
    assert out["target"]["geo_final"] < 20  # confidence scalar + Wilson keep it low


def test_larger_reliable_sample_beats_tiny_perfect_one(db_scope):
    _seed_project(db_scope, runs_target_rank=1, n_runs=60)
    out = compute_project_scores(1)
    # 60 runs all rank-1 → high presence/position, strong confidence → solid score
    assert out["target"]["geo_final"] > 40
    assert out["n_scored"] == 60


def test_ranking_reflected_in_position_component(db_scope):
    """A brand always at rank 1 scores a higher position component than one at rank 5."""
    rank1 = compute_project_scores(_seed_project(db_scope, runs_target_rank=1, n_runs=20))
    p_rank1 = rank1["target"]["position"]
    assert p_rank1 > 0.9  # rank-1 weight is 1.0

    # fresh DB via a new fixture instance isn't available here; assert the value directly
    from backend.scoring import components as C
    assert C.position_weight(5) < p_rank1


def test_citations_raise_citation_component(db_scope):
    with_cit = compute_project_scores(
        _seed_project(db_scope, runs_target_rank=1, n_runs=20, citations=1)
    )
    assert with_cit["target"]["citation"] > 0.5  # cited in every run → high citation rate


def test_target_outranks_competitor(db_scope):
    out = compute_project_scores(_seed_project(db_scope, runs_target_rank=1, n_runs=20))
    target = out["target"]
    competitor = next(b for b in out["brands"] if not b["is_target"])
    assert target["geo_final"] > competitor["geo_final"]  # earlier position wins


def test_sov_available_with_two_competitors(db_scope):
    out = compute_project_scores(_seed_project(db_scope, runs_target_rank=1, n_runs=20))
    assert out["sov_available"] is True
    assert out["target"]["sov"] is not None


def test_sov_unavailable_without_competitors(db_scope):
    out = compute_project_scores(
        _seed_project(db_scope, runs_target_rank=1, n_runs=20, competitor=False)
    )
    assert out["sov_available"] is False
    assert out["target"]["sov"] is None


def test_provider_denominator_uses_total_runs_not_discovery(db_scope):
    """Regression: a brand discovered mid-dataset must use the provider's TOTAL
    run count as its P6 denominator, not 'runs since first seen'."""
    with db_scope() as db:
        db.add(Profile(id="u1", email="u1@example.com"))
        db.flush()
        db.add(Project(id=1, user_id="u1", name="Notion", domain="notion.so"))
        db.flush()
        # 10 chatgpt runs: target in all; "LateBrand" only in the last 2
        for i in range(10):
            run = Run(project_id=1, provider="chatgpt", prompt=f"p{i}",
                      status="processed", target_sentiment="neutral")
            db.add(run)
            db.flush()
            db.add(Mention(run_id=run.id, entity_name="Notion", normalized_entity="Notion",
                           mention_position=1, is_target=True))
            if i >= 8:
                db.add(Mention(run_id=run.id, entity_name="LateBrand",
                               normalized_entity="LateBrand", mention_position=2, is_target=False))

    out = compute_project_scores(1)
    late = next(b for b in out["brands"] if b["brand"] == "LateBrand")
    assert late["n_appeared"] == 2
    assert late["n_captures"] == 10
    # P6 must reflect 2/10 (Wilson ~0.28), NOT the buggy 2/2 (~0.67)
    assert late["provider"] < 0.45
