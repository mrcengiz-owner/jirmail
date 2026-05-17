"""Kurulum profili normalizasyonu ve öneri mantığı (stdlib unittest)."""
import unittest

from installer.profiles import (
    PROFILE_COMPOSE_STACK,
    PROFILE_DOCKER_STACK,
    PROFILE_PLATFORM_ENV,
    PROFILE_PLATFORM_MANUAL,
    normalize_install_profile,
    suggested_profile_from_capabilities,
)


class InstallerProfilesTest(unittest.TestCase):
    def test_normalize_aliases(self):
        self.assertEqual(normalize_install_profile('coolify'), PROFILE_PLATFORM_ENV)
        self.assertEqual(normalize_install_profile('Dokploy'), PROFILE_PLATFORM_ENV)
        self.assertEqual(normalize_install_profile('cpanel'), PROFILE_PLATFORM_MANUAL)
        self.assertEqual(normalize_install_profile('docker'), PROFILE_DOCKER_STACK)
        self.assertEqual(normalize_install_profile('compose'), PROFILE_COMPOSE_STACK)
        self.assertEqual(normalize_install_profile('full_stack'), PROFILE_COMPOSE_STACK)

    def test_normalize_canonical_roundtrip(self):
        for p in (
            PROFILE_COMPOSE_STACK,
            PROFILE_DOCKER_STACK,
            PROFILE_PLATFORM_ENV,
            PROFILE_PLATFORM_MANUAL,
        ):
            self.assertEqual(normalize_install_profile(p), p)
            self.assertEqual(normalize_install_profile(p.upper()), p)

    def test_normalize_invalid(self):
        with self.assertRaises(ValueError) as ctx:
            normalize_install_profile('not_a_real_profile')
        self.assertIn('Bilinmeyen', str(ctx.exception))

    def test_normalize_empty(self):
        with self.assertRaises(ValueError):
            normalize_install_profile('')
        with self.assertRaises(ValueError):
            normalize_install_profile('   ')

    def test_suggested_profile_order(self):
        self.assertEqual(
            suggested_profile_from_capabilities({'compose_stack': True}),
            PROFILE_COMPOSE_STACK,
        )
        self.assertEqual(
            suggested_profile_from_capabilities(
                {'has_database_url': True, 'docker_available': False}
            ),
            PROFILE_PLATFORM_ENV,
        )
        self.assertEqual(
            suggested_profile_from_capabilities(
                {'has_database_url': False, 'docker_available': True}
            ),
            PROFILE_DOCKER_STACK,
        )
        self.assertEqual(
            suggested_profile_from_capabilities(
                {'has_database_url': False, 'docker_available': False}
            ),
            PROFILE_PLATFORM_MANUAL,
        )


if __name__ == '__main__':
    unittest.main()
