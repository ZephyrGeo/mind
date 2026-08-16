"use strict";

const { getApp, getApps, initializeApp } = require("firebase/app");
const {
  connectAuthEmulator,
  createUserWithEmailAndPassword,
  getAuth,
  onIdTokenChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut,
} = require("firebase/auth");

function localUser() {
  return {
    uid: "local-developer",
    email: null,
    displayName: "Local developer",
    emailVerified: true,
  };
}

function createLocalAuthService(token) {
  return {
    mode: "local",
    configured: true,
    subscribe(callback) {
      callback(localUser());
      return () => {};
    },
    async getToken() {
      return token;
    },
    async logout() {},
  };
}

function hasFirebaseConfig(config) {
  return Boolean(
    config?.apiKey &&
      config?.authDomain &&
      config?.projectId &&
      config?.appId,
  );
}

function createFirebaseAuthService(runtimeConfig) {
  const firebaseConfig = runtimeConfig.firebase;
  if (!hasFirebaseConfig(firebaseConfig)) {
    return {
      mode: "firebase",
      configured: false,
      configurationError:
        "Firebase web configuration is incomplete. Check the public runtime variables.",
    };
  }

  const appName = "mind-web";
  const app = getApps().some((candidate) => candidate.name === appName)
    ? getApp(appName)
    : initializeApp(firebaseConfig, appName);
  const auth = getAuth(app);
  if (runtimeConfig.firebaseAuthEmulatorUrl && !auth.emulatorConfig) {
    connectAuthEmulator(auth, runtimeConfig.firebaseAuthEmulatorUrl, {
      disableWarnings: true,
    });
  }

  return {
    mode: "firebase",
    configured: true,
    requireVerifiedEmail: Boolean(runtimeConfig.requireVerifiedEmail),
    subscribe(callback) {
      return onIdTokenChanged(auth, callback);
    },
    async register(email, password) {
      const credential = await createUserWithEmailAndPassword(
        auth,
        email,
        password,
      );
      await sendEmailVerification(credential.user);
      return credential.user;
    },
    async login(email, password) {
      const credential = await signInWithEmailAndPassword(auth, email, password);
      return credential.user;
    },
    async resetPassword(email) {
      await sendPasswordResetEmail(auth, email);
    },
    async resendVerification() {
      if (!auth.currentUser) throw new Error("No authenticated user.");
      await sendEmailVerification(auth.currentUser);
    },
    async refreshUser() {
      if (!auth.currentUser) return null;
      await auth.currentUser.reload();
      await auth.currentUser.getIdToken(true);
      return auth.currentUser;
    },
    async getToken() {
      if (!auth.currentUser) throw new Error("Authentication is required.");
      return auth.currentUser.getIdToken();
    },
    async logout() {
      await signOut(auth);
    },
  };
}

function createAuthService(runtimeConfig, localToken) {
  return runtimeConfig.authProvider === "firebase"
    ? createFirebaseAuthService(runtimeConfig)
    : createLocalAuthService(localToken);
}

module.exports = { createAuthService };
