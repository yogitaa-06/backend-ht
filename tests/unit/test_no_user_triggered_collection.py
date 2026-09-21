import inspect

from app.api.v1.routes import jobs, resumes


def test_user_routes_do_not_import_or_enqueue_collection_tasks() -> None:
    job_source = inspect.getsource(jobs)
    resume_source = inspect.getsource(resumes)

    assert "app.queue" not in job_source
    assert "enqueue_job" not in job_source
    assert "app.queue" not in resume_source
    assert "enqueue_job" not in resume_source
