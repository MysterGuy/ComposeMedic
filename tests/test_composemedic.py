import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from composemedic.checks import analyze, parse_port, selected_document
from composemedic.cli import main, parser, scan
from composemedic.docker import DockerError, live_checks, parse_records, run_readonly
from composemedic.loader import InputError, expand_values, interpolate, read_document, read_env
from composemedic.model import Report


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def check(self, services, **sections):
        report = Report()
        analyze({"services": services, **sections}, self.base, report)
        return report

    def codes(self, report):
        return {finding.code for finding in report.findings}

    def write(self, content, name="compose.yaml"):
        path = self.base / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_valid_stack_has_no_findings(self):
        (self.base / "data").mkdir()
        report = self.check({"api": {"image": "nginx:1.28", "ports": ["127.0.0.1:8080:80"], "volumes": ["./data:/data"]}})
        self.assertEqual(report.findings, [])

    def test_wildcard_port_collides_with_loopback(self):
        report = self.check({"a": {"image": "a:1", "ports": ["8080:80"]}, "b": {"image": "b:1", "ports": ["127.0.0.1:8080:80"]}})
        self.assertIn("PORT_COLLISION", self.codes(report))

    def test_different_addresses_and_protocols_do_not_collide(self):
        report = self.check({"a": {"image": "a:1", "ports": ["127.0.0.1:8080:80", "53:53/udp"]}, "b": {"image": "b:1", "ports": ["127.0.0.2:8080:80", "53:53/tcp"]}})
        self.assertNotIn("PORT_COLLISION", self.codes(report))

    def test_short_ranges_overlap(self):
        report = self.check({"a": {"image": "a:1", "ports": ["8000-8005:80-85"]}, "b": {"image": "b:1", "ports": ["8003:80"]}})
        self.assertIn("PORT_COLLISION", self.codes(report))

    def test_long_range_pool_is_warning_not_definite_collision(self):
        report = self.check({"a": {"image": "a:1", "ports": [{"target": 80, "published": "8000-8005"}]}, "b": {"image": "b:1", "ports": ["8003:80"]}})
        self.assertIn("PORT_POOL_OVERLAP", self.codes(report))
        self.assertNotIn("PORT_COLLISION", self.codes(report))

    def test_ephemeral_and_container_only_ports(self):
        for port in ("80", 80, "0:80", ":80", {"target": 80}, {"target": 80, "published": 0}):
            with self.subTest(port=port):
                self.assertIsNone(parse_port(port, "api", "ports"))

    def test_ipv6_and_bounds(self):
        port = parse_port("[::1]:8080:80", "api", "ports")
        self.assertEqual(port.ip, "::1")
        for invalid in ("70000:80", "8080:0", "10-12:80", "bad:8080:80", True):
            with self.subTest(port=invalid), self.assertRaises(ValueError):
                parse_port(invalid, "api", "ports")

    def test_missing_bind_is_warning_unless_creation_disabled(self):
        report = self.check({"a": {"image": "a:1", "volumes": ["./missing:/data"]}, "b": {"image": "b:1", "volumes": [{"type": "bind", "source": "./missing", "target": "/data", "bind": {"create_host_path": False}}]}})
        self.assertEqual([f.severity for f in report.findings], ["warning", "error"])

    def test_named_and_anonymous_volumes(self):
        report = self.check({"a": {"image": "a:1", "volumes": ["data:/data", "/cache"]}}, volumes={"data": None})
        self.assertEqual(report.findings, [])
        missing = self.check({"a": {"image": "a:1", "volumes": ["data:/data"]}})
        self.assertIn("VOLUME_UNDECLARED", self.codes(missing))

    def test_duplicate_mounts_and_invalid_targets(self):
        report = self.check({"a": {"image": "a:1", "volumes": ["/data", "cache:/data", "bad:relative"]}}, volumes={"cache": None})
        self.assertTrue({"MOUNT_TARGET_DUPLICATE", "MOUNT_INVALID"} <= self.codes(report))

    def test_windows_mount_is_not_split_at_drive_letter(self):
        from composemedic.checks import parse_mount
        kind, source, target, _ = parse_mount(r"C:\data:/app:ro")
        self.assertEqual((kind, source, target), ("bind", r"C:\data", "/app"))

    def test_required_and_optional_env_files(self):
        report = self.check({"a": {"image": "a:1", "env_file": [{"path": "missing", "required": False}]}})
        self.assertEqual(report.findings, [])
        report = self.check({"a": {"image": "a:1", "env_file": "missing"}})
        self.assertIn("ENV_FILE_MISSING", self.codes(report))

    def test_missing_build_context(self):
        report = self.check({"a": {"build": "./missing"}})
        self.assertIn("BUILD_CONTEXT_MISSING", self.codes(report))

    def test_remote_build_context_is_not_host_path(self):
        self.assertEqual(self.check({"a": {"build": "https://example.com/repo.git"}}).findings, [])

    def test_dependency_cycles(self):
        report = self.check({"a": {"image": "a:1", "depends_on": ["b"]}, "b": {"image": "b:1", "depends_on": ["a"]}})
        self.assertIn("DEPENDENCY_CYCLE", self.codes(report))

    def test_missing_optional_dependency_is_info(self):
        report = self.check({"a": {"image": "a:1", "depends_on": {"missing": {"required": False}}}})
        self.assertEqual(report.findings[0].severity, "info")

    def test_healthcheck_may_be_inherited_from_image(self):
        report = self.check({"a": {"image": "a:1", "depends_on": {"b": {"condition": "service_healthy"}}}, "b": {"image": "b:1"}})
        self.assertEqual(report.findings[0].code, "DEPENDENCY_HEALTH_UNVERIFIED")
        self.assertEqual(report.findings[0].severity, "warning")

    def test_active_healthcheck_satisfies_dependency(self):
        report = self.check({"a": {"image": "a:1", "depends_on": {"b": {"condition": "service_healthy"}}}, "b": {"image": "b:1", "healthcheck": {"test": ["CMD", "true"]}}})
        self.assertEqual(report.findings, [])

    def test_profiles_do_not_create_false_collisions(self):
        doc = {"services": {"a": {"image": "a:1", "ports": ["8080:80"]}, "b": {"image": "b:1", "ports": ["8080:80"], "profiles": ["debug"]}}}
        selected = selected_document(doc, set())
        self.assertEqual(list(selected["services"]), ["a"])
        report = Report(); analyze(selected, self.base, report)
        self.assertNotIn("PORT_COLLISION", self.codes(report))
        self.assertEqual(len(selected_document(doc, {"*"})["services"]), 2)

    def test_container_names_and_network_conflicts(self):
        report = self.check({"a": {"image": "a:1", "container_name": "same"}, "b": {"image": "b:1", "container_name": "same", "network_mode": "host", "ports": ["80:80"], "networks": ["missing"]}})
        self.assertTrue({"CONTAINER_NAME_COLLISION", "HOST_NETWORK_PORTS", "NETWORKS_UNDECLARED", "NETWORK_MODE_CONFLICT"} <= self.codes(report))

    def test_pinning_registry_port_is_not_image_tag(self):
        report = self.check({"a": {"image": "registry:5000/api"}, "b": {"image": "api:latest"}, "c": {"image": "api@sha256:abc"}})
        self.assertEqual(sum(f.code == "IMAGE_UNPINNED" for f in report.findings), 2)

    def test_missing_image_or_build(self):
        self.assertIn("IMAGE_OR_BUILD_MISSING", self.codes(self.check({"a": {}})))

    def test_interpolation_operators_nested_and_escaped(self):
        cases = {"${PORT:-8080}": "8080", "${PORT-${FALLBACK:-9090}}": "9090", "${SET:+yes}": "yes", "${EMPTY:+yes}": "", "${EMPTY-no}": "", "${EMPTY:-no}": "no", "$$PASSWORD": "$PASSWORD", "$SET": "value"}
        for expression, expected in cases.items():
            missing = set()
            self.assertEqual(interpolate(expression, {"SET": "value", "EMPTY": ""}, missing), expected)
            self.assertEqual(missing, set())

    def test_required_empty_and_missing_variables(self):
        missing = set()
        interpolate("${EMPTY:?do-not-print-this} $MISSING", {"EMPTY": ""}, missing)
        self.assertEqual(missing, {"EMPTY", "MISSING"})

    def test_env_values_are_never_reported(self):
        secret = "SENTINEL_SECRET_DO_NOT_LEAK"
        report = Report()
        expanded = expand_values({"services": {"a": {"image": "a:1", "volumes": ["${SECRET}:/data"], "command": "${MISSING:?" + secret + "}"}}}, {"SECRET": secret}, report)
        analyze(expanded, self.base, report)
        self.assertNotIn(secret, json.dumps(report.to_dict()))
        self.assertIn("ENV_UNSET", self.codes(report))

    def test_bad_yaml_error_does_not_echo_input(self):
        path = self.write("services:\n  api: [SENTINEL_SECRET\n")
        with self.assertRaises(InputError) as caught:
            read_document(path)
        self.assertNotIn("SENTINEL_SECRET", str(caught.exception))

    def test_duplicate_yaml_keys_are_rejected(self):
        with self.assertRaisesRegex(InputError, "Duplicate YAML key"):
            read_document(self.write("services:\n  api:\n    image: a:1\n    image: b:1\n"))

    def test_yaml_merge_defaults_work(self):
        doc = read_document(self.write("x-defaults: &defaults\n  image: a:1\nservices:\n  api:\n    <<: *defaults\n    image: b:1\n"))
        self.assertEqual(doc["services"]["api"]["image"], "b:1")

    def test_recursive_alias_rejected(self):
        value = {}; value["self"] = value
        with self.assertRaisesRegex(InputError, "Recursive"):
            expand_values(value, {}, Report())

    def test_dotenv_literals_and_comments(self):
        env = read_env(self.write("export PORT=8080 # note\nTOKEN='abc#def'\nEMPTY=\n", ".env"))
        self.assertEqual(env, {"PORT": "8080", "TOKEN": "abc#def", "EMPTY": ""})

    def test_bad_service_shape_is_input_error(self):
        path = self.write("services: [api]\n")
        with self.assertRaises(InputError):
            scan(parser().parse_args(["-f", str(path)]))

    def test_include_requires_canonical_resolution(self):
        path = self.write("include: [other.yaml]\nservices:\n  a:\n    image: a:1\n")
        with self.assertRaisesRegex(InputError, "require --resolve"):
            scan(parser().parse_args(["-f", str(path)]))

    def test_cli_json_exit_codes_and_readonly(self):
        path = self.write("services:\n  a:\n    image: a:1\n    ports: ['80:80']\n  b:\n    image: b:1\n    ports: ['80:80']\n")
        before = path.read_bytes()
        with patch("composemedic.docker.subprocess.run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
            result = main(["-f", str(path), "--format", "json"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())["summary"]["error"], 1)
        self.assertEqual(path.read_bytes(), before)
        run.assert_not_called()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["-f", str(path), "--fail-on", "never"]), 0)

    def test_cli_scan_error_is_json_and_exit_two(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = main(["-f", str(self.base / "missing"), "--format", "json"])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "SCAN_FAILED")

    def test_shell_overrides_dotenv(self):
        path = self.write("services:\n  a:\n    image: a:1\n    ports: ['${CM_TEST_PORT}:80']\n")
        self.write("CM_TEST_PORT=invalid\n", ".env")
        with patch.dict(os.environ, {"CM_TEST_PORT": "8080"}):
            report = scan(parser().parse_args(["-f", str(path)]))
        self.assertNotIn("PORT_INVALID", self.codes(report))

    def test_docker_json_lines_and_array(self):
        records = [{"Service": "api", "State": "running"}, {"Service": "db", "State": "exited"}]
        self.assertEqual(parse_records(json.dumps(records)), records)
        self.assertEqual(parse_records("\n".join(json.dumps(r) for r in records)), records)
        self.assertEqual(parse_records(""), [])

    def test_runtime_unhealthy_restart_successful_job_and_missing(self):
        doc = {"services": {name: {"image": "a:1"} for name in ("api", "db", "job", "missing")}}
        rows = [{"Service": "api", "State": "restarting", "Command": "SECRET"}, {"Service": "db", "State": "running", "Health": "unhealthy"}, {"Service": "job", "State": "exited", "ExitCode": 0}]
        report = Report(mode="live")
        with patch("composemedic.docker.run_readonly", return_value=json.dumps(rows)) as run:
            live_checks(["docker", "compose"], self.base, doc, report)
        self.assertTrue({"CONTAINER_FAILED", "CONTAINER_UNHEALTHY", "CONTAINER_EXITED", "CONTAINER_NOT_FOUND"} <= self.codes(report))
        self.assertNotIn("SECRET", json.dumps(report.to_dict()))
        self.assertEqual(run.call_args.args[0], ["docker", "compose", "ps", "--all", "--format", "json"])
        self.assertEqual(next(f.severity for f in report.findings if f.code == "CONTAINER_EXITED"), "info")

    def test_docker_failures_redact_stderr(self):
        result = subprocess.CompletedProcess([], 1, "", "PASSWORD=SECRET")
        with patch("composemedic.docker.subprocess.run", return_value=result) as run:
            with self.assertRaises(DockerError) as caught:
                run_readonly(["docker", "compose", "ps", "--all", "--format", "json"], self.base)
        self.assertNotIn("PASSWORD", str(caught.exception))
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_docker_lifecycle_commands_are_refused(self):
        with patch("composemedic.docker.subprocess.run") as run:
            for command in ("up", "down", "restart", "exec", "pull", "build"):
                with self.subTest(command=command), self.assertRaises(DockerError):
                    run_readonly(["docker", "compose", command], self.base)
        run.assert_not_called()

    def test_warning_threshold_and_malformed_input(self):
        path = self.write("services:\n  api:\n    image: nginx:latest\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["-f", str(path)]), 0)
            self.assertEqual(main(["-f", str(path), "--fail-on", "warning"]), 1)
        path = self.write("services:\n  api:\n    image: api:1\n    depends_on: [[invalid]]\n")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["-f", str(path), "--format", "json"]), 2)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "SCAN_FAILED")

    def test_resolved_multifile_uses_only_config_and_ps(self):
        a = self.write("services: {}", "compose.yaml")
        b = self.write("services: {}", "override.yaml")
        outputs = [json.dumps({"services": {"api": {"image": "api:1"}}}), json.dumps([{"Service": "api", "State": "running"}])]
        args = parser().parse_args(["-f", str(a), "-f", str(b), "--live", "-p", "example"])
        with patch("composemedic.docker.run_readonly", side_effect=outputs) as run:
            report = scan(args)
        self.assertEqual(report.mode, "live")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][-3:], ["config", "--format", "json"])
        self.assertEqual(commands[1][-4:], ["ps", "--all", "--format", "json"])
        self.assertTrue(all("--project-name" in cmd for cmd in commands))


if __name__ == "__main__":
    unittest.main()
