import assert from "node:assert/strict";
import test from "node:test";

import { deleteApp, initializeApp } from "firebase/app";
import {
  connectAuthEmulator,
  createUserWithEmailAndPassword,
  getAuth,
} from "firebase/auth";
import {
  connectFirestoreEmulator,
  doc,
  getDoc,
  getFirestore,
  setDoc,
} from "firebase/firestore";

const authHost = process.env.FIREBASE_AUTH_EMULATOR_HOST;
const firestoreHost = process.env.FIRESTORE_EMULATOR_HOST;
const emulatorAvailable = Boolean(authHost && firestoreHost);

function emulatorParts(value) {
  const [host, port] = value.split(":");
  return { host, port: Number(port) };
}

async function createClient(label) {
  const projectId = "demo-mind-local";
  const app = initializeApp(
    {
      apiKey: "demo-api-key",
      authDomain: `${projectId}.firebaseapp.com`,
      projectId,
      appId: `1:000000000000:web:${label}`,
    },
    `rules-${label}-${crypto.randomUUID()}`,
  );
  const auth = getAuth(app);
  connectAuthEmulator(auth, `http://${authHost}`, { disableWarnings: true });
  const database = getFirestore(app);
  const endpoint = emulatorParts(firestoreHost);
  connectFirestoreEmulator(database, endpoint.host, endpoint.port);
  return { app, auth, database };
}

test(
  "Firestore rules isolate each authenticated user subtree",
  { skip: !emulatorAvailable },
  async () => {
    const owner = await createClient("owner");
    const stranger = await createClient("stranger");
    const suffix = crypto.randomUUID();
    const ownerCredential = await createUserWithEmailAndPassword(
      owner.auth,
      `owner-${suffix}@example.test`,
      "local-test-password",
    );
    const strangerCredential = await createUserWithEmailAndPassword(
      stranger.auth,
      `stranger-${suffix}@example.test`,
      "local-test-password",
    );
    const ownerId = ownerCredential.user.uid;
    const strangerId = strangerCredential.user.uid;
    const ownerConversation = doc(
      owner.database,
      `users/${ownerId}/conversations/conversation-1`,
    );

    await setDoc(ownerConversation, {
      user_id: ownerId,
      title: "Owned conversation",
    });
    assert.equal((await getDoc(ownerConversation)).data().user_id, ownerId);

    await assert.rejects(
      setDoc(
        doc(
          stranger.database,
          `users/${ownerId}/conversations/conversation-2`,
        ),
        { user_id: strangerId, title: "Cross-tenant write" },
      ),
      (error) => error?.code === "permission-denied",
    );
    await assert.rejects(
      getDoc(
        doc(
          stranger.database,
          `users/${ownerId}/conversations/conversation-1`,
        ),
      ),
      (error) => error?.code === "permission-denied",
    );

    const ownerMemory = doc(
      owner.database,
      `users/${ownerId}/memories/memory-1`,
    );
    await setDoc(ownerMemory, {
      user_id: ownerId,
      content: "Owned memory",
      status: "active",
      enabled: true,
    });
    assert.equal((await getDoc(ownerMemory)).data().content, "Owned memory");
    await assert.rejects(
      getDoc(
        doc(stranger.database, `users/${ownerId}/memories/memory-1`),
      ),
      (error) => error?.code === "permission-denied",
    );

    await Promise.all([deleteApp(owner.app), deleteApp(stranger.app)]);
  },
);
