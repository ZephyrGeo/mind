from __future__ import annotations

import unittest
from unittest.mock import patch

from firebase_admin import exceptions

from backend.auth import FirebasePrincipalVerifier, IdentityVerificationError


class FirebasePrincipalVerifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = FirebasePrincipalVerifier(
            project_id="mind-auth-unit-test",
            check_revoked=True,
        )

    def test_permission_failure_maps_to_safe_server_configuration_error(self) -> None:
        with patch.object(
            self.verifier._auth,
            "verify_id_token",
            side_effect=exceptions.PermissionDeniedError("denied"),
        ):
            with self.assertRaises(IdentityVerificationError) as context:
                self.verifier.verify("opaque-token")

        self.assertEqual(
            context.exception.code,
            "authentication_server_misconfigured",
        )
        self.assertEqual(context.exception.status_code, 503)
        self.assertNotIn("denied", context.exception.message)

    def test_firebase_outage_maps_to_retryable_authentication_error(self) -> None:
        with patch.object(
            self.verifier._auth,
            "verify_id_token",
            side_effect=exceptions.UnavailableError("upstream unavailable"),
        ):
            with self.assertRaises(IdentityVerificationError) as context:
                self.verifier.verify("opaque-token")

        self.assertEqual(
            context.exception.code,
            "authentication_temporarily_unavailable",
        )
        self.assertEqual(context.exception.status_code, 503)
        self.assertNotIn("upstream", context.exception.message)


if __name__ == "__main__":
    unittest.main()
