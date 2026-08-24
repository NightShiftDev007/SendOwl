"""Deterministic graph memory for native research runs."""

from uuid import uuid4

from oasis_worker.research_memory import build_graph_memory, graph_memory_sha256
from oasis_worker.semantic_contracts import SemanticEvent


def test_graph_memory_extends_a_content_addressed_round_chain() -> None:
    persona_id = uuid4()
    first = build_graph_memory(
        "a" * 64,
        1,
        1,
        (
            SemanticEvent(
                round=1,
                phase="intervention",
                actor_kind="scenario",
                persona_id=None,
                agent_position=0,
                action_type="create_post",
                content="合成起始说明",
                post_id="post-1",
                comment_id=None,
                target_post_id=None,
                observed_at_raw="2026-08-18T00:00:00Z",
            ),
            SemanticEvent(
                round=1,
                phase="audience",
                actor_kind="persona",
                persona_id=persona_id,
                agent_position=1,
                action_type="like_post",
                content=None,
                post_id=None,
                comment_id=None,
                target_post_id="post-1",
                observed_at_raw="2026-08-18T00:01:00Z",
            ),
        ),
        None,
        None,
    )
    first_sha256 = graph_memory_sha256(first)
    second = build_graph_memory(
        "a" * 64,
        2,
        3,
        (
            SemanticEvent(
                round=2,
                phase="audience",
                actor_kind="persona",
                persona_id=persona_id,
                agent_position=1,
                action_type="create_comment",
                content="合成评论",
                post_id=None,
                comment_id="comment-1",
                target_post_id="post-1",
                observed_at_raw="2026-08-18T01:00:00Z",
            ),
        ),
        first,
        first_sha256,
    )

    assert second.previous_sha256 == first_sha256
    assert second.cumulative_event_count == 3
    assert [node.kind for node in second.nodes] == ["scenario", "post", "persona", "comment"]
    assert [edge.relation for edge in second.edges] == [
        "authored",
        "liked",
        "authored",
        "commented_on",
    ]
    assert graph_memory_sha256(second) == graph_memory_sha256(second)
