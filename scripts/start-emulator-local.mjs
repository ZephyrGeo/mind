// Start Mind against the local Firebase Auth and Firestore emulators.
Object.assign(process.env, {
  MIND_ENV: "development",
  MIND_AUTH_PROVIDER: "firebase",
  MIND_FIREBASE_PROJECT_ID: "demo-mind-local",
  MIND_ALLOWED_USER_EMAILS: "",
  MIND_REQUIRE_VERIFIED_EMAIL: "0",
  MIND_FIREBASE_CHECK_REVOKED: "0",
  MIND_PERSISTENCE_PROVIDER: "firestore",
  MIND_FIRESTORE_DATABASE_ID: "(default)",
  FIREBASE_AUTH_EMULATOR_HOST: "127.0.0.1:9099",
  FIRESTORE_EMULATOR_HOST: "127.0.0.1:8080",
  GOOGLE_CLOUD_PROJECT: "demo-mind-local",
  MIND_PUBLIC_AUTH_PROVIDER: "firebase",
  MIND_PUBLIC_REQUIRE_VERIFIED_EMAIL: "0",
  MIND_PUBLIC_FIREBASE_AUTH_EMULATOR_URL: "http://127.0.0.1:9099",
  MIND_PUBLIC_FIREBASE_API_KEY: "demo-api-key",
  MIND_PUBLIC_FIREBASE_AUTH_DOMAIN: "demo-mind-local.firebaseapp.com",
  MIND_PUBLIC_FIREBASE_PROJECT_ID: "demo-mind-local",
  MIND_PUBLIC_FIREBASE_APP_ID: "1:000000000000:web:demo",
});

await import("./start-local.mjs");
