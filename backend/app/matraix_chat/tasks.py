"""Frozen public definition of the integrated MatrAIx Acme source sample."""

from app.matraix_chat.contracts import MatraixChatTask

REST_TASK_ID = "matraix/acme-support-order-4521"
MCP_TASK_ID = "matraix/acme-support-mcp-order-4521"
TASK_VERSION = "1.0.0"
TASK_SCHEMA_VERSION = "matraix-chat-task/acme-support-v1"
FEEDBACK_SCHEMA_VERSION = "matraix-chat-feedback/acme-support-v1"
PROMPT_SCHEMA_VERSION = "matraix-chat-acme-support/v1"
RUNNER_VERSION = "1.0.0"
REST_SUT_SPEC_SHA256 = "b3609ac5ab58a4994c497f276d4689b8272150a9251676ddef84ebe9e8bdc980"
MCP_SUT_SPEC_SHA256 = "5fbc2623be9df873de0c025edd1f2dcbf9d0b24672d627f1e063002c9e9587e1"
CHAT_SUITE_ID = "sendowl/matraix-acme-rest-mcp-suite"
CHAT_SUITE_VERSION = "1.0.0"
CHAT_SUITE_SHA256 = "0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a"
# Stable aliases retained for the original REST source-sample contract.
TASK_ID = REST_TASK_ID
SUT_SPEC_SHA256 = REST_SUT_SPEC_SHA256

TASK_INSTRUCTION = (
    "Chat with Acme Support about the late NovaBuds Pro order #4521. Ask for what you "
    "need, react naturally to replies, and continue until you can judge whether support "
    "provided a useful resolution path. Have at least two back-and-forth exchanges and do "
    "not promise refunds or replacements you cannot verify."
)
TASK_CONTEXT = (
    "Order #4521 is for NovaBuds Pro wireless earbuds, placed last Thursday, promised for "
    "Tuesday, and still not delivered. The persona is contacting support about this delay."
)
REST_LIMITATIONS = (
    "Acme is a deterministic MatrAIx source sample used to exercise the evaluation path; "
    "it is not a production customer-support system.",
    "The first integrated version supports only the fixed REST text-chat task and cohorts "
    "containing one to eight sealed Personas.",
    "The experience rating is synthetic Persona self-report, not a benchmark reward or a "
    "claim about real customers.",
)
MCP_LIMITATIONS = (
    "Acme MCP is a deterministic MatrAIx source sample used to exercise the fixed "
    "streamable-HTTP tool path; it is not a production customer-support system.",
    "Only the fixed send_message tool on the isolated Compose service is callable; "
    "user-provided MCP endpoints and arbitrary tools are not exposed.",
    "The experience rating is synthetic Persona self-report, not a benchmark reward or a "
    "claim about real customers.",
)


def task_without_digest(task_id: str) -> dict[str, object]:
    """Return the complete task identity included in its content address."""
    return {
        "task_id": task_id,
        "version": TASK_VERSION,
        "schema_version": TASK_SCHEMA_VERSION,
        "title": "Acme support: late order #4521",
        "domain": "commerce-retail",
        "source": {
            "kind": "source_sample",
            "project": "MatrAIx",
            "canonical_path": (
                "application/tasks/example-chat-mcp_support_chatbot"
                if task_id == MCP_TASK_ID
                else "application/tasks/example-chat-api_support_chatbot"
            ),
            "production_sut": False,
        },
        "application_id": "acme_support_mcp" if task_id == MCP_TASK_ID else "acme_support_api",
        "application_context": "customer_support",
        "transport": "mcp_streamable_http" if task_id == MCP_TASK_ID else "sidecar_http",
        "capabilities": ("text_chat", "mcp_tool") if task_id == MCP_TASK_ID else ("text_chat",),
        "instruction": TASK_INSTRUCTION,
        "context": TASK_CONTEXT,
        "minimum_customer_turns": 2,
        "minimum_total_messages": 4,
        "feedback_schema_version": FEEDBACK_SCHEMA_VERSION,
        "sut_spec_sha256": (
            MCP_SUT_SPEC_SHA256 if task_id == MCP_TASK_ID else REST_SUT_SPEC_SHA256
        ),
        "limitations": MCP_LIMITATIONS if task_id == MCP_TASK_ID else REST_LIMITATIONS,
    }


def build_chat_task(task_id: str) -> MatraixChatTask:
    """Build the validated task projection with its immutable digest."""
    from app.matraix_chat.hashing import calculate_task_spec_sha256

    if task_id not in {REST_TASK_ID, MCP_TASK_ID}:
        raise ValueError(f"unsupported fixed MatrAIx Chat task {task_id}")
    payload = task_without_digest(task_id)
    return MatraixChatTask(
        **payload,
        task_spec_sha256=calculate_task_spec_sha256(payload),
    )


def build_chat_tasks() -> tuple[MatraixChatTask, MatraixChatTask]:
    return (build_chat_task(REST_TASK_ID), build_chat_task(MCP_TASK_ID))
