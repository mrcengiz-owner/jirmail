"""Mail stack otomatik doğrulama birim testleri."""
import unittest

from management.mail_stack_health import (
    build_postfix_pgsql_cf,
    run_mail_stack_self_test,
    validate_postfix_pgsql_cf,
)


class MailStackHealthTest(unittest.TestCase):
    def test_valid_multiline_pgsql_cf(self):
        content = build_postfix_pgsql_cf(
            db_host="postgres",
            db_port=5432,
            db_user="postgres",
            db_pass="Murat1993.",
            db_name="jir_mail_prod",
            query="SELECT 1",
        )
        ok, msg = validate_postfix_pgsql_cf(content)
        self.assertTrue(ok, msg)
        self.assertIn("dbname = jir_mail_prod", content)
        self.assertIn("password = Murat1993.", content)

    def test_rejects_broken_single_line_hosts(self):
        broken = "hosts = host=postgres port=5432 dbname= user=u password=secret\nquery = SELECT 1\n"
        ok, _ = validate_postfix_pgsql_cf(broken)
        self.assertFalse(ok)

    def test_self_test_bundle(self):
        result = run_mail_stack_self_test()
        self.assertTrue(result["ok"])
        self.assertTrue(result["valid_sample"])
        self.assertTrue(result["rejects_broken_hosts_line"])


if __name__ == "__main__":
    unittest.main()
