function indexCollectionGroup(index) {
  if (typeof index?.name !== "string") {
    return undefined;
  }

  return index.name.match(/\/collectionGroups\/([^/]+)\/indexes\//)?.[1];
}

export function hasMemoryVectorIndex(indexes, dimensions) {
  if (!Array.isArray(indexes)) {
    return false;
  }

  return indexes.some(
    (index) =>
      indexCollectionGroup(index) === "memories" &&
      index.queryScope === "COLLECTION" &&
      index.fields?.some(
        (field) =>
          field.fieldPath === "embedding" &&
          Number(field.vectorConfig?.dimension) === dimensions,
      ),
  );
}

export function isAlreadyExistsError(stderr) {
  return (
    typeof stderr === "string" &&
    /(?:^|\s)ALREADY_EXISTS(?::|\s|$)/.test(stderr)
  );
}
