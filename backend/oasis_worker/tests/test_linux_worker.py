"""Fixed MatrAIx Linux worker contracts and cross-package golden hashes."""

from oasis_worker.linux_contracts import LinuxFileHashes, LinuxSubmission
from oasis_worker.linux_hashing import linux_config_sha256, result_sha256, trial_sha256


def test_linux_trial_and_result_hashes_match_control_plane_golden_values() -> None:
    trial = trial_sha256(
        "0a4bf540dec44e3ea488a2884eb1b4d3233470616e87c9ff370847b0509155a9",
        "ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354",
        "31000000-0000-4000-8000-000000000001",
        "a" * 64,
        "b" * 64,
        "32000000-0000-4000-8000-000000000001",
        0,
        "linux-persona",
        "c" * 64,
        "qwen-plus",
        "d" * 64,
        "matraix-linux-note-to-csv/v1",
    )
    files = LinuxFileHashes(
        cleaned_list_csv="e" * 64,
        submission_json="f" * 64,
        user_feedback_json="1" * 64,
        verifier_json="2" * 64,
    )

    assert trial == "401f2a90b112c3b4b168ce398243f8eb315f6a63c8677cab698f0954d685cb75"
    assert (
        result_sha256(
            trial,
            "3" * 64,
            files,
            "The fixed rows are normalized into the requested three-column CSV.",
            "yes",
            "yes",
            8,
            "The output is clear and directly usable.",
        )
        == "d0761bc3b1ca34787af2fc6bea37f37ae5745f896473ecf80256a2761961a69e"
    )


def test_linux_runtime_hash_binds_provider_identity_and_submission_is_strict() -> None:
    assert linux_config_sha256("https://provider.example/v1", "qwen") != linux_config_sha256(
        "https://provider.example/v1", "qwen-plus"
    )
    submission = LinuxSubmission(
        reason="The fixed rows map directly to the requested CSV columns.",
        need_constraint_satisfaction="yes",
        personal_preference_satisfaction="partially",
        overall_experience_rating=7,
        feedback_reason="The fixed output is useful for this sample.",
    )
    assert submission.overall_experience_rating == 7
