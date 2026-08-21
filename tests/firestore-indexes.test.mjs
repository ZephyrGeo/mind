import assert from "node:assert/strict";
import test from "node:test";

import {
  hasMemoryVectorIndex,
  isAlreadyExistsError,
} from "../scripts/firestore-indexes.mjs";

function vectorIndex(overrides = {}) {
  return {
    queryScope: "COLLECTION",
    fields: [
      { fieldPath: "__name__", order: "ASCENDING" },
      {
        fieldPath: "embedding",
        vectorConfig: { dimension: 256, flat: {} },
      },
    ],
    ...overrides,
  };
}

test("recognizes the collection group in the official resource name", () => {
  const indexes = [
    vectorIndex({
      name: "projects/mind/databases/(default)/collectionGroups/memories/indexes/CICAgOjXh4EK",
    }),
  ];

  assert.equal(hasMemoryVectorIndex(indexes, 256), true);
});

test("rejects indexes for another collection or vector dimension", () => {
  const wrongCollection = vectorIndex({
    name: "projects/mind/databases/(default)/collectionGroups/messages/indexes/example",
  });
  const wrongDimension = vectorIndex({
    name: "projects/mind/databases/(default)/collectionGroups/memories/indexes/example",
    fields: [
      {
        fieldPath: "embedding",
        vectorConfig: { dimension: 768, flat: {} },
      },
    ],
  });

  assert.equal(hasMemoryVectorIndex([wrongCollection], 256), false);
  assert.equal(hasMemoryVectorIndex([wrongDimension], 256), false);
  assert.equal(hasMemoryVectorIndex(undefined, 256), false);
});

test("does not accept a non-standard collectionGroup field", () => {
  const indexes = [vectorIndex({ collectionGroup: "memories" })];

  assert.equal(hasMemoryVectorIndex(indexes, 256), false);
});

test("only accepts the structured ALREADY_EXISTS error code", () => {
  assert.equal(
    isAlreadyExistsError(
      "ERROR: (gcloud.firestore.indexes.composite.create) ALREADY_EXISTS: index already exists",
    ),
    true,
  );
  assert.equal(isAlreadyExistsError("index already exists"), false);
  assert.equal(isAlreadyExistsError("PERMISSION_DENIED: access denied"), false);
});
