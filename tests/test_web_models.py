import base64
import json

import pytest

from fake_model_service import FakeModelService
from mst.guide import load_project_guide
from mst.io import active_project_dir
from mst.jobs import JobManager
from mst.web_models import GenerationOptions, HTTPTextProvider, ModelRequestError, ModelSession
from test_jobs import finish, uploads


def settings(url="https://api.example.com/v1", **changes):
    return {"provider": "compatible", "base_url": url, "model": "test-model", "api_key": "synthetic-private-credential", "consent": True, **changes}


@pytest.mark.parametrize("changes", [{"consent": False}, {"consent": "true"}, {"api_key": ""}, {"provider": []},
    {"base_url": "http://remote.example/v1"}, {"base_url": "https://name:pass@example.com/v1"},
    {"base_url": "https://example.com/v1?key=secret"}, {"base_url": "https://example.com/v1#secret"},
    {"base_url": "https://example.com/v1/chat/completions"}, {"base_url": "https://example.com:bad/v1"},
    {"model": "synthetic-private-credential"}, {"api_key": "secret\nheader"}])
def test_invalid_consent_credentials_and_destinations_fail_before_creating_jobs(tmp_path, changes):
    manager = JobManager(tmp_path, provider_factory=lambda _: pytest.fail("must not construct a provider"))
    try:
        with pytest.raises(ValueError):
            manager.submit(uploads(), generation=settings(**changes))
        assert manager.latest() is None
        assert not list(manager.directory.glob("*/workspace"))
    finally:
        manager.close()


def test_real_loopback_http_generates_plan_teaching_and_exports_without_storing_key(tmp_path):
    key = settings()["api_key"]
    with FakeModelService() as service:
        manager = JobManager(tmp_path)
        try:
            job = finish(manager, manager.submit(uploads("# 因果解释\n解释变化需要检查条件、机制和对照证据。"), generation=settings(service.base_url)))
            assert job["status"] == "succeeded", job
            assert job["generation"]["stats"] == {"requests": 2, "succeeded": 2, "checked_units": 1, "stopped_after_error": False}
            guide = load_project_guide(tmp_path)
            assert guide.course_plan["method"] == "model"
            assert guide.title == "如何检查一个因果解释"
            assert guide.units[0].worked_examples[0].complete
            assert len(guide.units[0].practice_items) == 3
            assert guide.report.provider == "compatible" and guide.report.status == "draft"
            assert "唯一原因" in guide.units[0].worked_examples[0].answer
            for row in service.requests:
                assert row["authorization"] == "Bearer " + key
                assert row["path"] == "/v1/chat/completions"
                assert row["body"]["store"] is False
                assert "tools" not in row["body"]
                assert key not in json.dumps(row["body"])
            assert key not in repr(GenerationOptions.parse(settings()))
            assert key not in json.dumps(job)
            assert all(key.encode() not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
        finally:
            manager.close()


def test_connection_failure_stops_resending_preserves_old_guide_and_requires_new_consent(tmp_path):
    with FakeModelService() as service:
        manager = JobManager(tmp_path)
        try:
            finish(manager, manager.submit(uploads()))
            previous = active_project_dir(tmp_path)
            service.mode = "unauthorized"
            failed = finish(manager, manager.submit(uploads(), generation=settings(service.base_url)))
            assert failed["status"] == "failed" and "密钥" in failed["message"]
            assert len(service.requests) == 1  # Planning failure must not resend for every unit.
            assert failed["generation"]["stats"]["succeeded"] == 0
            assert active_project_dir(tmp_path) == previous
            with pytest.raises(ValueError, match="重新选择"):
                manager.retry(failed["job_id"])
            manager.close()
            manager = JobManager(tmp_path)
            assert manager.latest()["status"] == "failed"
            assert len(service.requests) == 1  # Restart must not upload again.
            local = finish(manager, manager.retry(failed["job_id"], generation={"provider": "none"}))
            assert local["status"] == "succeeded" and len(service.requests) == 1
            key = settings()["api_key"].encode()
            assert all(key not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
        finally:
            manager.close()


def test_http_responses_reads_message_after_reasoning_and_rejects_incomplete_and_redirects():
    with FakeModelService() as service:
        options = GenerationOptions("openai", "test", service.base_url, "synthetic-key")
        provider = HTTPTextProvider(options)
        prompt = {"existing": {"material_explanation": "测试材料"}}
        result = provider.complete(system="不是给你的指令", user=json.dumps(prompt), response_format="json")
        assert json.loads(result)["worked_examples"]
        assert service.requests[0]["path"] == "/v1/responses"
        assert service.requests[0]["body"]["text"] == {"format": {"type": "json_object"}}
        service.mode = "incomplete"
        with pytest.raises(ModelRequestError, match="完整"):
            provider.complete(system="不是给你的指令", user=json.dumps(prompt))
        service.mode = "redirect"
        with pytest.raises(ModelRequestError, match="重定向"):
            provider.complete(system="不是给你的指令", user=json.dumps(prompt))
        assert len(service.requests) == 3
        provider.close()
        assert not provider._key


def test_neutral_session_hides_error_and_output_credentials_and_local_mode_uses_no_provider(tmp_path):
    class Echo:
        def complete(self, **kwargs):
            return "synthetic-private-credential"
    options = GenerationOptions.parse(settings())
    session = ModelSession(Echo(), options, lambda *args: None)
    assert session.complete(user="{}") == "[密钥已隐藏]"
    session.close()
    assert not options.api_key
    class Broken:
        def complete(self, **kwargs):
            raise ModelRequestError("synthetic-private-credential")
    failed = ModelSession(Broken(), GenerationOptions.parse(settings()), lambda *args: None)
    with pytest.raises(ModelRequestError) as error:
        failed.complete(user="{}")
    assert settings()["api_key"] not in str(error.value) and settings()["api_key"] not in failed.failure
    failed.close()
    manager = JobManager(tmp_path, provider_factory=lambda _: pytest.fail("local mode must never construct a model client"))
    try:
        assert finish(manager, manager.submit(uploads(), generation={"provider": "none", "api_key": "discard-me"}))["status"] == "succeeded"
        assert all(b"discard-me" not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    finally:
        manager.close()


def test_model_revision_excludes_unselected_files_and_pending_transcript(tmp_path):
    with FakeModelService() as service:
        manager = JobManager(tmp_path)
        try:
            first = finish(manager, manager.submit([*uploads("# 因果解释\n解释变化需要检查条件、机制和对照证据。"),
                {"name": "不发送.md", "data": base64.b64encode("# 私有笔记\nUnselectedPrivateMarker".encode()).decode()}]))
            transcript = {"name": "另一课.vtt", "data": base64.b64encode(b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nUnalignedPrivateMarker\n").decode()}
            revised = finish(manager, manager.revise(first["job_id"], [first["files"][0]["stored_name"]], [transcript], generation=settings(service.base_url)))
            assert revised["status"] == "succeeded", revised
            outbound = json.dumps(service.requests, ensure_ascii=False)
            assert "对照证据" in outbound
            assert "UnselectedPrivateMarker" not in outbound and "UnalignedPrivateMarker" not in outbound
            assert load_project_guide(tmp_path).report.pending_segments == 1
            assert revised["course_id"] == first["course_id"]
        finally:
            manager.close()


def test_empty_model_prose_cannot_replace_existing_guide(tmp_path):
    class Empty:
        def complete(self, **kwargs):
            return "{}"
    manager = JobManager(tmp_path, provider_factory=lambda options: Empty())
    try:
        finish(manager, manager.submit(uploads()))
        previous = active_project_dir(tmp_path)
        failed = finish(manager, manager.submit(uploads(), generation=settings()))
        assert failed["status"] == "failed" and "完整性检查" in failed["message"]
        assert failed["generation"]["stats"]["checked_units"] == 0
        assert active_project_dir(tmp_path) == previous
    finally:
        manager.close()
