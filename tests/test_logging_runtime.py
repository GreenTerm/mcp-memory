from __future__ import annotations

import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp_memory.logging_utils import RuntimeLogFormatter, configure_logging, log_event, shutdown_logging


class LoggingRuntimeTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_logging()

    def test_configure_logging_writes_to_expected_file(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "logs" / "component.log"
            logger = configure_logging("api", "INFO", log_path)
            log_event(logger, logging.INFO, "server_start", host="127.0.0.1", port=8765)
            for handler in logger.handlers:
                handler.flush()

            self.assertTrue(log_path.exists())
            contents = log_path.read_text(encoding="utf-8")
            self.assertIn("INFO api server_start", contents)
            self.assertIn("host=127.0.0.1", contents)
            self.assertIn("port=8765", contents)
            shutdown_logging()

    def test_formatter_emits_plain_text_fields(self) -> None:
        formatter = RuntimeLogFormatter()
        record = logging.LogRecord("mcp_memory.cli", logging.INFO, __file__, 10, "", (), None)
        record.component = "cli"
        record.event = "command_finish"
        record.fields = {"command": "list-projects", "status": "ok"}
        rendered = formatter.format(record)
        self.assertIn("INFO cli command_finish", rendered)
        self.assertIn("command=list-projects", rendered)
        self.assertIn("status=ok", rendered)

    def test_configure_logging_replaces_handlers_instead_of_duplicating(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "logs" / "component.log"
            logger = configure_logging("services", "INFO", log_path)
            first_handler_count = len(logger.handlers)
            logger = configure_logging("services", "INFO", log_path)
            second_handler_count = len(logger.handlers)
            log_event(logger, logging.INFO, "project_created", project_id="p1")
            for handler in logger.handlers:
                handler.flush()

            contents = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(first_handler_count, second_handler_count)
            self.assertEqual(len(contents), 1)
            shutdown_logging()


if __name__ == "__main__":
    unittest.main()
