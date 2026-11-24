window.GOLDEN=[
 {
  "id": "Q1",
  "type": "relational",
  "question": "I see RELATION_OWNED_BY and RELATION_OWNER_OF defined together in relations.ts. When I write owner: group:default/platform in my catalog-info.yaml, who actually creates the reverse side of that relationship — and how does the system know to emit both directions?",
  "answer": "The reverse side is created by BuiltinKindsEntityProcessor, not by the user. In its postProcessEntity method, when the entity kind is Component (or any kind that declares spec.owner), it reads spec.owner, parses it with parseEntityRef using the textual [kind:][namespace/]name format documented in ADR-009, and then calls doEmit twice — once with RELATION_OWNED_BY pointing from the component to the group, and once with the paired RELATION_OWNER_OF pointing from the group back to the component. The two constants are declared together in relations.ts precisely to signal that they are a bidirectional pair; the processor is responsible for emitting both sides in a single processing pass.",
  "gold_files": [
   "docs/architecture-decisions/adr009-entity-references.md",
   "packages/catalog-model/src/kinds/relations.ts",
   "packages/catalog-model/src/kinds/ComponentEntityV1alpha1.ts",
   "plugins/catalog-backend/src/processors/BuiltinKindsEntityProcessor.ts"
  ],
  "chain": "spec.owner field (ComponentEntityV1alpha1) -> textual ref format (adr009) -> constant names (relations.ts) -> processor emits both directions (BuiltinKindsEntityProcessor.doEmit)"
 },
 {
  "id": "Q2",
  "type": "relational",
  "question": "My catalog-info.yaml has no namespace field at all, but the entity shows up as default/component/my-service. Where does the string 'default' come from — is it hardcoded in ten places? And is the resulting namespace actually validated, or just silently added?",
  "answer": "The string 'default' comes from a single canonical declaration: DEFAULT_NAMESPACE = 'default' in packages/catalog-model/src/entity/constants.ts. It is not hardcoded elsewhere. ADR-002 establishes that namespace is optional (Kubernetes-inspired). DefaultNamespaceEntityPolicy imports DEFAULT_NAMESPACE and uses lodash.merge to inject it when metadata.namespace is absent. The result is then validated — the DefaultCatalogProcessingOrchestrator chains DefaultNamespaceEntityPolicy first, then FieldFormatEntityPolicy, which validates namespace naming/format rules against the newly-injected value. So the answer is: one constant, injected by one policy, validated by the next policy in the chain.",
  "gold_files": [
   "docs/architecture-decisions/adr002-default-catalog-file-format.md",
   "packages/catalog-model/src/entity/constants.ts",
   "packages/catalog-model/src/entity/policies/DefaultNamespaceEntityPolicy.ts",
   "packages/catalog-model/src/entity/policies/FieldFormatEntityPolicy.ts",
   "plugins/catalog-backend/src/processing/DefaultCatalogProcessingOrchestrator.ts"
  ],
  "chain": "ADR says optional (adr002) -> constant defined once (constants.ts) -> policy injects it (DefaultNamespaceEntityPolicy) -> next policy validates it (FieldFormatEntityPolicy) -> orchestrator wires the chain"
 },
 {
  "id": "Q3",
  "type": "how-X-works",
  "question": "What validation rules does FieldFormatEntityPolicy apply to entity metadata fields like name, namespace and labels — and where do those rules actually live?",
  "answer": "FieldFormatEntityPolicy.enforce iterates the entity's identifying fields (kind, apiVersion, metadata.name, metadata.namespace, metadata.labels, metadata.annotations, metadata.tags) and delegates each to a specific validator function imported from packages/catalog-model/src/validation. Those validators enforce Kubernetes-style rules (isValidObjectName for DNS-label-like names, isValidLabelKey/isValidLabelValue for k8s label semantics, plus common tag/annotation formats). The policy does not embed the regexes itself — it composes validators — so a full answer requires both FieldFormatEntityPolicy.ts and the validators library. The unit test file documents the error-message contract for each field.",
  "gold_files": [
   "packages/catalog-model/src/entity/policies/FieldFormatEntityPolicy.ts",
   "packages/catalog-model/src/validation/index.ts",
   "packages/catalog-model/src/entity/policies/FieldFormatEntityPolicy.test.ts"
  ],
  "chain": "policy.enforce iterates fields -> delegates to Kubernetes/Common validator functions -> throws on format violation; test file documents error-message contract"
 },
 {
  "id": "Q4",
  "type": "how-X-works",
  "question": "How does PlaceholderProcessor resolve $file, $text and $json references inside a catalog-info.yaml, and how does it decide which resolver to call?",
  "answer": "PlaceholderProcessor recursively walks the entity JSON. When it encounters an object with exactly one key that begins with '$' (e.g. { $file: '...' }), it treats that key's suffix as a resolver name and looks it up in a resolver map. The resolver reads the referenced URL via the UrlReaderService, parses the payload according to its format ($file returns raw text, $text explicitly returns text, $json parses as JSON, $yaml parses as YAML), and the parsed value replaces the placeholder object in the entity tree. The resolver map itself is not defined in the processor — it is registered in CatalogBuilder, which is what wires the default set of resolvers into the processor at startup.",
  "gold_files": [
   "plugins/catalog-backend/src/processors/PlaceholderProcessor.ts",
   "plugins/catalog-backend/src/service/CatalogBuilder.ts"
  ],
  "chain": "entity JSON traversed -> $-prefixed key found -> resolver map lookup -> resolver reads URL via UrlReaderService -> parsed value merged back; resolvers registered in CatalogBuilder"
 },
 {
  "id": "Q5",
  "type": "how-X-works",
  "question": "When a Location entity has type: file with a glob target, which processor picks it up and how does it turn the glob into a set of emitted entities?",
  "answer": "FileReaderProcessor handles it. During the orchestrator's runSpecialLocationStep, each registered LocationProcessor is asked whether it claims the given location.type; FileReaderProcessor claims type === 'file'. It resolves the target path, uses a glob library to expand it into concrete file paths, reads each file, parses it as one or more YAML entities, and emits them via the processing emit function so they flow into the rest of the pipeline. The processor is registered on the CatalogBuilder — without that registration the orchestrator would have no handler for file-type locations.",
  "gold_files": [
   "plugins/catalog-backend/src/processors/FileReaderProcessor.ts",
   "plugins/catalog-backend/src/processing/DefaultCatalogProcessingOrchestrator.ts",
   "plugins/catalog-backend/src/service/CatalogBuilder.ts"
  ],
  "chain": "orchestrator runSpecialLocationStep iterates registered processors -> FileReaderProcessor claims 'file' type -> glob matches paths -> parsed entities emitted"
 },
 {
  "id": "Q6",
  "type": "relational",
  "question": "If a Component's spec has system: platforms pointing at a System entity, what relations get emitted in each direction, and where is that pairing declared?",
  "answer": "Two relations are emitted: RELATION_PART_OF from the Component to the System, and its reverse RELATION_HAS_PART from the System back to the Component. Both are emitted by BuiltinKindsEntityProcessor.postProcessEntity when it processes a Component whose spec.system is set: it parses the target as an entity ref (defaulting kind to System) and calls doEmit for each direction. The constant pair PART_OF / HAS_PART is declared together in packages/catalog-model/src/kinds/relations.ts, mirroring the OWNED_BY / OWNER_OF pattern.",
  "gold_files": [
   "packages/catalog-model/src/kinds/ComponentEntityV1alpha1.ts",
   "packages/catalog-model/src/kinds/SystemEntityV1alpha1.ts",
   "packages/catalog-model/src/kinds/relations.ts",
   "plugins/catalog-backend/src/processors/BuiltinKindsEntityProcessor.ts"
  ],
  "chain": "Component.spec.system -> BuiltinKindsProcessor -> emits PART_OF (component->system) + HAS_PART (system->component); constants paired in relations.ts"
 },
 {
  "id": "Q7",
  "type": "relational",
  "question": "A Group has both spec.parent and spec.children fields. How does the system reconcile these with RELATION_PARENT_OF / RELATION_CHILD_OF, and what stops a Group with neither from creating an orphan tree?",
  "answer": "BuiltinKindsEntityProcessor emits CHILD_OF for each Group's spec.parent (group -> parent-group) and PARENT_OF for each entry in spec.children (group -> child-group). Because the stitching layer merges relations from all providers, having both fields populated on both sides is idempotent — the same edges just get emitted twice and deduplicated. The orphan case is handled by GroupDefaultParentEntityPolicy: if a Group has no spec.parent, the policy injects a default root-parent reference before the processor runs, guaranteeing every Group has at least one CHILD_OF edge and the group tree stays connected.",
  "gold_files": [
   "packages/catalog-model/src/kinds/GroupEntityV1alpha1.ts",
   "packages/catalog-model/src/kinds/relations.ts",
   "plugins/catalog-backend/src/processors/BuiltinKindsEntityProcessor.ts",
   "packages/catalog-model/src/entity/policies/GroupDefaultParentEntityPolicy.ts"
  ],
  "chain": "Group.spec.parent -> CHILD_OF emitted; Group.spec.children -> PARENT_OF emitted (both by BuiltinKindsEntityProcessor); GroupDefaultParentEntityPolicy injects root parent when missing to keep tree connected"
 },
 {
  "id": "Q8",
  "type": "relational",
  "question": "When a User entity has memberOf: [group:infra], which two relations are created and by which code path?",
  "answer": "Two relations are created: RELATION_MEMBER_OF from the User to the Group, and the reverse RELATION_HAS_MEMBER from the Group back to the User. Both are emitted by BuiltinKindsEntityProcessor.postProcessEntity when it iterates User.spec.memberOf, parses each entry as an entity ref (defaulting kind to Group), and calls doEmit for each direction. The relation constants are paired in relations.ts.",
  "gold_files": [
   "packages/catalog-model/src/kinds/UserEntityV1alpha1.ts",
   "packages/catalog-model/src/kinds/relations.ts",
   "plugins/catalog-backend/src/processors/BuiltinKindsEntityProcessor.ts"
  ],
  "chain": "User.spec.memberOf -> BuiltinKindsEntityProcessor.postProcessEntity -> emits MEMBER_OF (user->group) + HAS_MEMBER (group->user)"
 },
 {
  "id": "Q9",
  "type": "relational",
  "question": "If Component A declares consumesApis: [api:payment] and Component B declares providesApis: [api:payment], how many relations end up in the graph and what does each direction look like?",
  "answer": "Four relations, two per Component. From A: RELATION_CONSUMES_API (A -> API) and RELATION_API_CONSUMED_BY (API -> A). From B: RELATION_PROVIDES_API (B -> API) and RELATION_API_PROVIDED_BY (API -> B). All four are emitted by BuiltinKindsEntityProcessor when it processes each Component's spec.providesApis and spec.consumesApis arrays — each entry is parsed as an entity ref (defaulting kind to API) and doEmit is called for both directions of the pair.",
  "gold_files": [
   "packages/catalog-model/src/kinds/ComponentEntityV1alpha1.ts",
   "packages/catalog-model/src/kinds/relations.ts",
   "plugins/catalog-backend/src/processors/BuiltinKindsEntityProcessor.ts"
  ],
  "chain": "Component.spec.{providesApis,consumesApis} -> BuiltinKindsEntityProcessor emits four total: CONSUMES_API+API_CONSUMED_BY between A<->API, PROVIDES_API+API_PROVIDED_BY between B<->API"
 },
 {
  "id": "Q10",
  "type": "relational",
  "question": "How does an EntityProvider actually get its entities into the database — what does applyMutation do, and what envelope-level validation happens on the way in?",
  "answer": "Each EntityProvider is bound to an EntityProviderConnection whose applyMutation method is the entry point. When the provider calls applyMutation with either a 'full' or 'delta' mutation, the connection runs validateEntityEnvelope on each supplied entity — this checks required top-level fields (apiVersion, kind, metadata.name) and rejects malformed envelopes before they ever touch the database. Valid entities are then persisted via ProviderDatabase.replaceUnprocessedEntities inside a transaction, keyed by the provider's unique name so a later mutation from the same provider replaces its previous set atomically. The persistence contract is defined in database/types.ts and the mutation shape in processing/types.ts.",
  "gold_files": [
   "plugins/catalog-backend/src/processing/connectEntityProviders.ts",
   "plugins/catalog-backend/src/processing/types.ts",
   "plugins/catalog-backend/src/database/types.ts"
  ],
  "chain": "provider mutation -> EntityProviderConnection.applyMutation -> validateEntityEnvelope -> ProviderDatabase.replaceUnprocessedEntities inside transaction"
 },
 {
  "id": "Q11",
  "type": "relational",
  "question": "During entity processing, which orchestration step actually invokes the entity policies, and how are multiple policies composed into one call?",
  "answer": "The orchestrator's runPolicyStep is the invocation point. Rather than calling each policy individually, the orchestrator holds a single composite EntityPolicy built with EntityPolicies.allOf(...), which wraps the list of concrete policies (DefaultNamespaceEntityPolicy, FieldFormatEntityPolicy, SchemaValidEntityPolicy, NoForeignRootFieldsEntityPolicy, etc.) into one .enforce call. The composite runs each policy in registration order, passing the entity output of one as the input to the next, so a policy that injects fields (like DefaultNamespaceEntityPolicy) runs before a policy that validates them (like FieldFormatEntityPolicy). The EntityPolicy interface itself is defined in packages/catalog-model/src/entity/policies/types.ts.",
  "gold_files": [
   "plugins/catalog-backend/src/processing/DefaultCatalogProcessingOrchestrator.ts",
   "packages/catalog-model/src/entity/policies/types.ts",
   "packages/catalog-model/src/entity/policies/EntityPolicies.ts"
  ],
  "chain": "orchestrator.runPolicyStep -> composite EntityPolicies.allOf -> individual policy.enforce calls in order"
 },
 {
  "id": "Q12",
  "type": "relational",
  "question": "How does CatalogRulesEnforcer stop somebody from ingesting a User or Group entity from an arbitrary URL location — and where are the default allow-rules defined?",
  "answer": "The defaults live in plugins/catalog-backend/src/ingestion/CatalogRules.ts as defaultRules, which allow only Component, API, and Location kinds from any location — User and Group are deliberately absent from that allow-list. During processing, DefaultCatalogProcessingOrchestrator calls rulesEnforcer.isAllowed(entity, originLocation) after entities are emitted; if the entity's kind is not permitted for its origin location, the enforcer raises NotAllowedError and the entity is dropped. The enforcer is wired into the pipeline in CatalogBuilder, so an operator can override the defaults by supplying their own rules there.",
  "gold_files": [
   "plugins/catalog-backend/src/ingestion/CatalogRules.ts",
   "plugins/catalog-backend/src/processing/DefaultCatalogProcessingOrchestrator.ts",
   "plugins/catalog-backend/src/service/CatalogBuilder.ts"
  ],
  "chain": "defaultRules in CatalogRules.ts allow-list Component/API/Location only -> orchestrator calls rulesEnforcer.isAllowed(entity, originLocation) post-emit -> NotAllowedError raised on disallowed kinds; enforcer wired in CatalogBuilder"
 },
 {
  "id": "Q13",
  "type": "relational",
  "question": "If I remove an EntityProvider from my backend, what happens to the entities it previously registered? Are they orphaned or actively cleaned up?",
  "answer": "They are actively cleaned up on startup by evictEntitiesFromOrphanedProviders, which CatalogBuilder invokes as part of catalog initialisation. The function queries ProviderDatabase.listReferenceSourceKeys to get every provider name that owns rows in the database, then diffs that against the set of provider names actually registered in the running backend. Any provider names present in the DB but not in the active set are considered orphaned; for each, replaceUnprocessedEntities is called with an empty array, which removes their unprocessed rows. On the next stitching pass, the now-referenceless final entities are cleaned up as well, so removed providers do not leak entities.",
  "gold_files": [
   "plugins/catalog-backend/src/processing/evictEntitiesFromOrphanedProviders.ts",
   "plugins/catalog-backend/src/database/types.ts",
   "plugins/catalog-backend/src/service/CatalogBuilder.ts"
  ],
  "chain": "on startup, CatalogBuilder invokes evictEntitiesFromOrphanedProviders -> compares db.listReferenceSourceKeys vs active providers -> orphaned providers get replaceUnprocessedEntities([]) -> their entities disappear on next stitch"
 },
 {
  "id": "Q14",
  "type": "relational",
  "question": "When AnnotateLocationEntityProcessor sees a Location URL that already contains a commit hash, why does it deliberately NOT set the edit-url annotation?",
  "answer": "A commit-pinned URL points to an immutable snapshot of source (e.g. .../blob/<40-char sha>/...). Editing that URL in a hosted-git UI would not update the referenced content — commits are immutable — so an edit-url would be misleading. AnnotateLocationEntityProcessor's preProcessEntity uses commitHashRegExp to detect a hex commit hash in the target; if it matches, editUrl is left undefined and only the ANNOTATION_VIEW_URL and source-location annotations are set. The annotation-key constants (ANNOTATION_EDIT_URL, ANNOTATION_VIEW_URL, etc.) live in packages/catalog-model/src/kinds/annotations.ts.",
  "gold_files": [
   "plugins/catalog-backend/src/processors/AnnotateLocationEntityProcessor.ts",
   "packages/catalog-model/src/kinds/annotations.ts"
  ],
  "chain": "location.type === 'url' -> commitHashRegExp.test(target) -> if match, editUrl left undefined (a commit-pinned URL isn't editable) -> only viewUrl + sourceLocation annotations set; annotation constants live in annotations.ts"
 },
 {
  "id": "Q15",
  "type": "relational",
  "question": "How does the stitcher decide which entities need their relations recomputed, and what marks an entity as needing a re-stitch after processing?",
  "answer": "The signal is a per-entity stitch_ticket column in the database. After an entity finishes post-processing, the markForStitching operation sets a new ticket value on that entity's row. The DefaultStitcher runs a loop that calls getDeferredStitchableEntities, which returns entities whose stitch_ticket has not yet been reconciled with the current stitched state. For each such entity, stitchOne re-reads its emitted relations from every provider that contributes to that final entity, combines them, and writes the synthesised final entity + relations back to the database. The StitchingStrategy type in stitching/types.ts governs how eagerly this loop runs (deferred vs immediate).",
  "gold_files": [
   "plugins/catalog-backend/src/stitching/DefaultStitcher.ts",
   "plugins/catalog-backend/src/database/operations/stitcher/getDeferredStitchableEntities.ts",
   "plugins/catalog-backend/src/database/operations/stitcher/markForStitching.ts",
   "plugins/catalog-backend/src/stitching/types.ts"
  ],
  "chain": "post-processing sets stitch_ticket via markForStitching -> DefaultStitcher polls getDeferredStitchableEntities -> stitchOne synthesises final relations from all providers for that entity"
 },
 {
  "id": "Q16",
  "type": "relational",
  "question": "How does CodeOwnersProcessor decide whether it should even look at a given entity — which kinds is it allowed to touch, and which location types trigger it?",
  "answer": "CodeOwnersProcessor.preProcessEntity applies a three-clause guard before doing any work. First, entity.kind must be in ALLOWED_KINDS = ['API', 'Component', 'Domain', 'Resource', 'System']. Second, the entity's origin location must have location.type === 'url' (ALLOWED_LOCATION_TYPES). Third, spec.owner must be falsy — if the entity already declares an owner, the processor does nothing so it never overrides an explicit choice. Only when all three conditions hold does the processor fetch the CODEOWNERS file from the repo and resolve an owner from it. The processor is registered in CatalogBuilder alongside the other built-in processors.",
  "gold_files": [
   "plugins/catalog-backend/src/processors/CodeOwnersProcessor.ts",
   "plugins/catalog-backend/src/service/CatalogBuilder.ts"
  ],
  "chain": "preProcessEntity guards: entity.kind in ALLOWED_KINDS (API/Component/Domain/Resource/System) AND location.type === 'url' AND spec.owner falsy -> only then reads CODEOWNERS; processor registered in CatalogBuilder"
 },
 {
  "id": "Q17",
  "type": "relational",
  "question": "How does ModelProcessor emit relations declared by the entity kind's schema, and what part of the model layer tells it which fields are relation-bearing?",
  "answer": "ModelProcessor is a data-driven counterpart to BuiltinKindsEntityProcessor. In postProcessEntity, it looks up the entity's kind in the model layer (built by createCatalogModelLayer) to get the kind's schema, which includes a relationFields array. Each relationField describes a spec-path selector, the relation constant to emit, and a defaultKind for parseEntityRef. The processor iterates relationFields, uses lodash.get to pull the value from the entity at each selector's path, parses each entry as an entity ref, and emits the corresponding relation via processingResult.relation. Because the emission logic is schema-driven, adding a new relation to a kind only requires editing that kind's file (e.g. ComponentEntityV1alpha1) — no processor change needed. ModelProcessor is registered in CatalogBuilder.",
  "gold_files": [
   "plugins/catalog-backend/src/processors/ModelProcessor.ts",
   "packages/catalog-model/src/model/createCatalogModelLayer.ts",
   "packages/catalog-model/src/kinds/ComponentEntityV1alpha1.ts",
   "plugins/catalog-backend/src/service/CatalogBuilder.ts"
  ],
  "chain": "entity.kind looked up in model layer -> relationFields[] from kind schema -> lodash.get on each field -> parseEntityRef -> processingResult.relation emitted; ModelProcessor wired in CatalogBuilder"
 },
 {
  "id": "Q18",
  "type": "failure-mode",
  "question": "What happens if a policy or processor mutates the entity's kind mid-pipeline — say a policy accidentally rewrites kind: Component to kind: API? Is that caught, and where?",
  "answer": "Yes, it is caught by DefaultCatalogProcessingOrchestrator. Before running the policy and pre-processing steps, the orchestrator computes stringifyEntityRef on the incoming entity and holds it as the expected identity. After each step, it recomputes the ref on the entity that came back and compares to the expected string. If they differ — because kind, namespace, or name was mutated — the orchestrator throws a ConflictError prefixed with 'Fatal:' indicating that the entity ref changed during processing, which fails the entity's processing pass and prevents the mutated identity from being persisted. The stringifyEntityRef utility itself lives in processing/util.ts.",
  "gold_files": [
   "plugins/catalog-backend/src/processing/DefaultCatalogProcessingOrchestrator.ts",
   "packages/catalog-model/src/entity/Entity.ts",
   "plugins/catalog-backend/src/processing/util.ts"
  ],
  "chain": "orchestrator captures stringifyEntityRef pre-policy -> after policy step, recomputes ref -> mismatch throws ConflictError 'Fatal: entity ref changed'"
 },
 {
  "id": "Q19",
  "type": "failure-mode",
  "question": "If an entity YAML has an unknown top-level field like foo: bar next to spec/metadata, does it get silently dropped, ignored, or rejected — and by whom?",
  "answer": "It is rejected, not dropped or ignored. NoForeignRootFieldsEntityPolicy.enforce iterates Object.keys(entity) and checks each against a hard-coded whitelist of known root fields (apiVersion, kind, metadata, spec, relations, status). Any key outside that set causes the policy to throw an error naming the offending field. The policy is part of the default entity-policy chain (registered via packages/catalog-model/src/entity/policies/index.ts), so it runs on every entity — a stray foo: bar will fail policy enforcement and the entity will not be persisted.",
  "gold_files": [
   "packages/catalog-model/src/entity/policies/NoForeignRootFieldsEntityPolicy.ts",
   "packages/catalog-model/src/entity/policies/index.ts"
  ],
  "chain": "NoForeignRootFieldsEntityPolicy.enforce iterates Object.keys(entity) -> any key outside {apiVersion, kind, metadata, spec, relations, status} -> throws with the offending field name; policy is part of the default chain"
 },
 {
  "id": "Q20",
  "type": "failure-mode",
  "question": "If my YAML contains $unknownPlaceholder (a placeholder key that nobody registered a resolver for), does ingestion fail, or does the value pass through as-is?",
  "answer": "It passes through as-is — the behaviour is fail-open, not fail-closed. PlaceholderProcessor's process function looks up the '$'-suffixed key in its resolver map; if resolvers[key] is undefined, it returns the containing object unchanged instead of throwing. The comment in the code explicitly justifies this as 'erring on the side of caution' so that unknown placeholders don't break ingestion. The set of registered resolvers ($file, $text, $json, $yaml by default) is defined in CatalogBuilder, and only keys in that set are actually resolved — everything else survives into the persisted entity untouched.",
  "gold_files": [
   "plugins/catalog-backend/src/processors/PlaceholderProcessor.ts",
   "plugins/catalog-backend/src/service/CatalogBuilder.ts"
  ],
  "chain": "JSON traversal finds $-key -> resolvers[key] === undefined -> value returned unchanged (fail-open, not fail-closed); registered resolvers set in CatalogBuilder"
 },
 {
  "id": "Q21",
  "type": "failure-mode",
  "question": "When an entity fails AJV schema validation via SchemaValidEntityPolicy, what does the error message look like — does it point at the failing field, or just say 'malformed'?",
  "answer": "It points at the failing field. SchemaValidEntityPolicy compiles the JSON schema from packages/catalog-model/src/schema/Entity.schema.json using Ajv at construction time. In enforce, it runs the compiled validator against the entity; on failure, it reads the first entry in validator.errors, which is an AJV ErrorObject with an instancePath (e.g. '/metadata/name') and a message (e.g. 'must match pattern ...'), and throws an error formatted as 'Malformed envelope, {instancePath} {message}'. So the caller gets both a field pointer and a human-readable constraint description, not a generic 'malformed' string.",
  "gold_files": [
   "packages/catalog-model/src/entity/policies/SchemaValidEntityPolicy.ts",
   "packages/catalog-model/src/schema/Entity.schema.json"
  ],
  "chain": "ajv.compile(schema) -> validate(entity) === false -> first error object read -> error thrown as 'Malformed envelope, {instancePath} {message}'; schema shape lives in Entity.schema.json"
 },
 {
  "id": "U1",
  "type": "unanswerable-plausible-absent",
  "question": "How does the CachingProcessor use ETags to avoid re-reading unchanged entity sources across refresh cycles?",
  "answer": null,
  "gold_files": [],
  "chain": "Term 'CachingProcessor' does not exist in the corpus. Verified zero occurrences (case-insensitive) across ingest/backstage/."
 },
 {
  "id": "U2",
  "type": "unanswerable-plausible-absent",
  "question": "What does RefreshValidatorPolicy check when an entity requests a manual refresh via the API?",
  "answer": null,
  "gold_files": [],
  "chain": "Term 'RefreshValidatorPolicy' does not exist in the corpus. Verified zero occurrences (case-insensitive)."
 },
 {
  "id": "U3",
  "type": "unanswerable-plausible-absent",
  "question": "How does LocationProviderRegistry coordinate multiple location sources to prevent duplicate entity registration?",
  "answer": null,
  "gold_files": [],
  "chain": "Term 'LocationProviderRegistry' does not exist in the corpus. Verified zero occurrences (case-insensitive)."
 },
 {
  "id": "U4",
  "type": "unanswerable-homonym",
  "question": "How does Backstage's Location entity system handle geographic coordinates and physical office addresses when mapping team sites?",
  "answer": null,
  "gold_files": [],
  "chain": "Homonym trap. 'Location' in Backstage means a catalog registration URL (Location kind entity, spec.type + spec.target). It has nothing to do with physical geography. Naive retrievers will surface Location entity docs and hallucinate that they describe geographic coordinates."
 },
 {
  "id": "U5",
  "type": "unanswerable-off-topic",
  "question": "How does Backstage's tokenizer split entity descriptions when fine-tuning a language model to auto-generate catalog metadata?",
  "answer": null,
  "gold_files": [],
  "chain": "Backstage does not train, fine-tune, or tokenise for language models. It is a developer portal / service catalog. Off-topic."
 },
 {
  "id": "U6",
  "type": "unanswerable-off-topic",
  "question": "Which scheduling algorithm does Backstage use to decide which Kubernetes node hosts a given catalog entity's backing pod?",
  "answer": null,
  "gold_files": [],
  "chain": "Kubernetes scheduling is external infrastructure. Backstage's kubernetes plugin displays cluster state, it does not implement or configure the scheduler. Off-topic."
 },
 {
  "id": "U7",
  "type": "unanswerable-off-topic",
  "question": "How does Backstage's internal npm registry decide when to purge old package versions from its storage backend?",
  "answer": null,
  "gold_files": [],
  "chain": "Backstage does not run an npm registry. It publishes packages to public npm. Off-topic."
 },
 {
  "id": "U8",
  "type": "unanswerable-off-topic",
  "question": "How does the React Fiber reconciler in Backstage's frontend prioritise re-renders when the entity list updates?",
  "answer": null,
  "gold_files": [],
  "chain": "React Fiber is a React-internal algorithm. Backstage consumes React but does not implement or customise the reconciler. Off-topic."
 },
 {
  "id": "U9",
  "type": "unanswerable-off-topic",
  "question": "What algorithm does Backstage's TypeScript compiler use for structural type inference in generic entity types like Entity<TSpec>?",
  "answer": null,
  "gold_files": [],
  "chain": "TypeScript compiler internals live in microsoft/TypeScript, not in this repo. Backstage is written in TypeScript, it does not implement TypeScript. Off-topic."
 },
 {
  "id": "U10",
  "type": "unanswerable-off-topic",
  "question": "How does Backstage's GraphQL federation gateway stitch subgraphs from multiple catalog plugins into one unified schema?",
  "answer": null,
  "gold_files": [],
  "chain": "Backstage does not use GraphQL federation. Its catalog API is REST/OpenAPI. Off-topic."
 }
];
