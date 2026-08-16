"""Authentication boundaries for local development and Firebase deployments."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .models import LocalPrincipal


@dataclass(slots=True)
class IdentityVerificationError(Exception):
    """A safe authentication or access-control failure."""

    code: str
    message: str
    status_code: int = 401

    def __str__(self) -> str:
        return self.message


class PrincipalVerifier(Protocol):
    """Resolve an opaque bearer token to one authenticated Mind principal."""

    method: str

    def verify(self, token: str) -> LocalPrincipal:
        ...


class AccountManager(Protocol):
    """Delete an authenticated identity after its Mind data is cleaned up."""

    def delete_user(self, user_id: str) -> None:
        ...


class LocalAccountManager:
    """Local identities are configuration, so only their data is deleted."""

    def delete_user(self, user_id: str) -> None:
        del user_id


class LocalTokenPrincipalVerifier:
    """Development/test verifier retained for the zero-cost local workflow."""

    method = "local_token"

    def __init__(self, *, expected_token: str, user_id: str) -> None:
        self.expected_token = expected_token
        self.user_id = user_id

    def verify(self, token: str) -> LocalPrincipal:
        if not hmac.compare_digest(token, self.expected_token):
            raise IdentityVerificationError(
                code="authentication_required",
                message="A valid local token is required.",
            )
        return LocalPrincipal(
            user_id=self.user_id,
            display_name="Local developer",
            authentication_method=self.method,
        )


class FirebasePrincipalVerifier:
    """Verify Firebase ID tokens without exposing Firebase to API services."""

    method = "firebase"

    def __init__(
        self,
        *,
        project_id: str,
        allowed_user_emails: tuple[str, ...] = (),
        require_verified_email: bool = True,
        check_revoked: bool = True,
    ) -> None:
        try:
            import firebase_admin
            from firebase_admin import auth, exceptions
        except ImportError as error:  # pragma: no cover - packaging guard
            raise RuntimeError(
                "firebase-admin is required when MIND_AUTH_PROVIDER=firebase."
            ) from error

        self._auth = auth
        self._firebase_exceptions = exceptions
        self.project_id = project_id
        self.allowed_user_emails = frozenset(
            email.casefold() for email in allowed_user_emails
        )
        self.require_verified_email = require_verified_email
        self.check_revoked = check_revoked
        app_name = f"mind-{project_id}"
        try:
            self._app = firebase_admin.get_app(app_name)
        except ValueError:
            self._app = firebase_admin.initialize_app(
                options={"projectId": project_id},
                name=app_name,
            )

    def verify(self, token: str) -> LocalPrincipal:
        try:
            claims = self._auth.verify_id_token(
                token,
                app=self._app,
                check_revoked=self.check_revoked,
            )
        except self._auth.CertificateFetchError as error:
            raise IdentityVerificationError(
                code="authentication_temporarily_unavailable",
                message="Authentication is temporarily unavailable. Please retry.",
                status_code=503,
            ) from error
        except self._firebase_exceptions.PermissionDeniedError as error:
            raise IdentityVerificationError(
                code="authentication_server_misconfigured",
                message=(
                    "Mind authentication is not configured correctly on the server."
                ),
                status_code=503,
            ) from error
        except (
            self._auth.InvalidIdTokenError,
            self._auth.ExpiredIdTokenError,
            self._auth.RevokedIdTokenError,
            self._auth.UserDisabledError,
            ValueError,
        ) as error:
            raise IdentityVerificationError(
                code="authentication_required",
                message="A valid Firebase ID token is required.",
            ) from error
        except self._firebase_exceptions.FirebaseError as error:
            raise IdentityVerificationError(
                code="authentication_temporarily_unavailable",
                message="Authentication is temporarily unavailable. Please retry.",
                status_code=503,
            ) from error

        user_id = str(claims.get("uid") or claims.get("sub") or "").strip()
        if not user_id:
            raise IdentityVerificationError(
                code="authentication_required",
                message="The Firebase ID token does not identify a user.",
            )

        email_claim = claims.get("email")
        email = str(email_claim).strip() if email_claim else None
        email_verified = bool(claims.get("email_verified", False))
        if self.require_verified_email and not email_verified:
            raise IdentityVerificationError(
                code="email_verification_required",
                message="Verify your email address before using Mind.",
                status_code=403,
            )
        if self.allowed_user_emails and (
            email is None or email.casefold() not in self.allowed_user_emails
        ):
            raise IdentityVerificationError(
                code="access_not_allowed",
                message="This account is not allowed to access Mind.",
                status_code=403,
            )

        auth_time_claim = claims.get("auth_time")
        auth_time = None
        if isinstance(auth_time_claim, (int, float)):
            auth_time = datetime.fromtimestamp(auth_time_claim, timezone.utc)

        name_claim = claims.get("name")
        return LocalPrincipal(
            user_id=user_id,
            email=email,
            display_name=str(name_claim).strip() if name_claim else None,
            email_verified=email_verified,
            authenticated_at=auth_time,
            authentication_method=self.method,
        )

    def delete_user(self, user_id: str) -> None:
        """Delete the Firebase identity using the same initialized Admin app."""

        try:
            self._auth.delete_user(user_id, app=self._app)
        except self._auth.UserNotFoundError:
            return
