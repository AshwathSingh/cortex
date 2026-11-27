from importlib.metadata import PackageNotFoundError
import pytest
from scripts import check_environment


def test_locked_install_detects_dependency_drift(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("fastapi==0.141.1 \\\n    --hash=sha256:test\n")
    monkeypatch.setattr(check_environment, "version", lambda name: "0.1.0")
    with pytest.raises(RuntimeError, match="does not satisfy"):
        check_environment.verify_requirements(requirements)


def test_missing_package_has_setup_guidance(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.in"
    requirements.write_text("fastapi\n")

    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(check_environment, "version", missing)
    with pytest.raises(RuntimeError, match="missing; run npm run setup"):
        check_environment.verify_requirements(requirements)


def test_unrelated_platform_requirements_do_not_require_installation(
    tmp_path, monkeypatch
):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("not-a-real-package==1; python_version < '1'\n")
    monkeypatch.setattr(
        check_environment,
        "version",
        lambda name: pytest.fail("Inactive marker was checked"),
    )
    check_environment.verify_requirements(requirements)
