import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def test_hoshikage_profile_model_and_token_are_passed_to_codex(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    bin_dir = app_root / "bin"
    workspace = app_root / "workspace"
    fake_path = tmp_path / "fake-path"
    bin_dir.mkdir(parents=True)
    workspace.mkdir()
    fake_path.mkdir()

    launcher = bin_dir / "yatagarasu"
    shutil.copy2(PROJECT_ROOT / "bin" / "yatagarasu", launcher)
    write_executable(
        bin_dir / "zunda",
        "#!/bin/bash\ncat\n",
    )
    write_executable(
        bin_dir / "tapovoice",
        "#!/bin/bash\ncat >/dev/null\n",
    )
    write_executable(
        fake_path / "codex",
        """#!/bin/bash
printf '%s\\n' "$@" > "$CODEX_ARGS_CAPTURE"
printf '%s' "${HOSHIKAGE_API_KEY:-}" > "$CODEX_TOKEN_CAPTURE"
printf '%s' "$PATH" > "$CODEX_PATH_CAPTURE"
output_file=""
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-o" ]]; then
        output_file="$2"
        shift 2
    else
        shift
    fi
done
printf 'OK\\n' > "$output_file"
""",
    )

    args_capture = tmp_path / "args.txt"
    token_capture = tmp_path / "token.txt"
    path_capture = tmp_path / "path.txt"
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_path}:{env['PATH']}",
            "YATAGARASU_ENGINE": "codex",
            "YATAGARASU_CODEX_PROFILE": "yatagarasu-local",
            "YATAGARASU_CODEX_MODEL": "unsloth-gemma4-12b-qat-thinking-off",
            "YATAGARASU_MEMORY_ENABLED": "false",
            "HOSHIKAGE_API_KEY": "test-secret-token",
            "CODEX_ARGS_CAPTURE": str(args_capture),
            "CODEX_TOKEN_CAPTURE": str(token_capture),
            "CODEX_PATH_CAPTURE": str(path_capture),
        }
    )

    subprocess.run(
        [str(launcher), "Return exactly OK."],
        cwd=workspace,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    args = args_capture.read_text().splitlines()
    assert args[args.index("--profile") + 1] == "yatagarasu-local"
    assert args[args.index("-m") + 1] == "unsloth-gemma4-12b-qat-thinking-off"
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert "--dangerously-bypass-approvals-and-sandbox" not in args
    assert token_capture.read_text() == "test-secret-token"
    assert path_capture.read_text().split(":")[0] == str(home / ".local" / "bin")


def test_codex_profile_is_optional_for_existing_providers() -> None:
    launcher = (PROJECT_ROOT / "bin" / "yatagarasu").read_text()

    assert "YATAGARASU_CODEX_PROFILE" in launcher
    assert 'codex_args+=(--profile "$CODEX_PROFILE")' in launcher


def test_recall_skill_uses_repository_executable_path() -> None:
    skill = (
        PROJECT_ROOT / "workspace" / ".codex" / "skills" / "recall" / "SKILL.md"
    ).read_text()

    assert ".codex/skills/recall/scripts/recall.sh" in skill
    assert "\nrecall \"" not in skill


def test_launcher_doctor_defaults_to_project_workspace(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    bin_dir = app_root / "bin"
    workspace = app_root / "workspace"
    caller = tmp_path / "caller"
    bin_dir.mkdir(parents=True)
    workspace.mkdir()
    caller.mkdir()

    shutil.copy2(PROJECT_ROOT / "bin" / "yatagarasu", bin_dir / "yatagarasu")
    write_executable(
        bin_dir / "yatagarasu-doctor",
        "#!/bin/bash\nprintf '%s' \"$YATAGARASU_CWD\"\n",
    )

    env = os.environ.copy()
    env.pop("YATAGARASU_CWD", None)
    result = subprocess.run(
        [str(bin_dir / "yatagarasu"), "doctor"],
        cwd=caller,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == str(workspace)


def test_doctor_validates_authenticated_hoshikage_profile(tmp_path: Path) -> None:
    class ReadyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if (
                self.path == "/ready"
                and self.headers.get("Authorization") == "Bearer test-secret-token"
            ):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ready"}')
                return
            self.send_response(401)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReadyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        app_root = tmp_path / "app"
        bin_dir = app_root / "bin"
        workspace = app_root / "workspace"
        codex_home = tmp_path / "codex-home"
        fake_path = tmp_path / "fake-path"
        bin_dir.mkdir(parents=True)
        workspace.mkdir()
        codex_home.mkdir()
        fake_path.mkdir()

        doctor = bin_dir / "yatagarasu-doctor"
        shutil.copy2(PROJECT_ROOT / "bin" / "yatagarasu-doctor", doctor)
        write_executable(bin_dir / "zunda", "#!/bin/bash\nexit 0\n")
        write_executable(bin_dir / "tapovoice", "#!/bin/bash\nexit 0\n")
        for command in ("codex", "ffmpeg", "uv"):
            write_executable(fake_path / command, "#!/bin/bash\nexit 0\n")

        profile = codex_home / "yatagarasu-local.config.toml"
        profile.write_text(
            f"""
model = "unsloth-gemma4-12b-qat-thinking-off"
model_provider = "hoshikage"

[model_providers.hoshikage]
base_url = "http://127.0.0.1:{server.server_port}/v1"
wire_api = "responses"
env_key = "HOSHIKAGE_API_KEY"

[sandbox_workspace_write]
network_access = true
"""
        )
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_path}:/usr/bin:/bin",
                "CODEX_HOME": str(codex_home),
                "YATAGARASU_ENGINE": "codex",
                "YATAGARASU_CODEX_PROFILE": "yatagarasu-local",
                "HOSHIKAGE_API_KEY": "test-secret-token",
            }
        )

        result = subprocess.run(
            [str(doctor), "--no-services", "--no-logs"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        assert "codex profile: yatagarasu-local" in result.stdout
        assert "Hoshikage provider: responses" in result.stdout
        assert "Hoshikage token: configured" in result.stdout
        assert "Codex sandbox network: enabled" in result.stdout
        assert "Hoshikage ready:" in result.stdout
        assert "test-secret-token" not in result.stdout
    finally:
        server.shutdown()
        thread.join()
