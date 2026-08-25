# A hub is a connection; agents carry the models — design

**Date:** 2026-08-25
**Status:** awaiting the user's review
**Breaking:** yes, for anyone whose entry still relies on the legacy single agent

---

## 1. The decision

A config entry is a **connection to a provider** and nothing more: credentials,
endpoint, and the few switches that belong to the connection itself. Every
conversation agent — its model, prompt, temperature, tools, entity context — is
a subentry the user creates deliberately.

This is the user's call, stated plainly, and the code already half agrees with
it. What follows is mostly deletion.

## 2. What is actually there today

The hub-creation flow already collects only connection details: an API key, a
folder id, a base URL, `skip_validation`. **Nothing about a model is asked when
a provider is connected.** So the flow needs no change.

The duplication lives in `OptionsFlow.async_step_settings`, which edits
`entry.options` using **the same `subentry_schema` an agent uses** — model,
prompt, temperature, tools, the lot. Those options drive exactly one thing:

```python
    if subentries:
        ...one entity per conversation subentry...
    else:
        # Legacy mode: single entity from entry.options
        entities.append(SmartChainConversationEntity(config_entry))
```

The legacy entity exists **only when an entry has no conversation subentries**.
The same `if subentries: ... else:` shape governs client construction in
`async_setup_entry`.

**So for anyone who has created an agent, `entry.options` is dead
configuration** — a form that saves values which are never read. The user's own
entry demonstrates it: `options` holds a complete agent config naming
`GigaChat-3-Ultra`, alongside two real agents, and a stale
`conversation.smartchain_<entry_id>` sits in the entity registry from before the
subentries existed.

That is worse than duplication. Duplication is confusing; this is a control that
looks live and is not.

## 3. What changes

**`OptionsFlow` keeps only what belongs to the connection.** For GigaChat that
is `verify_ssl` and `profanity`; every other provider has nothing, and its
options step should say so rather than present an empty form. Model, prompt,
temperature, `llm_hass_api`, tools, history and entity-context settings all
leave — they are agent properties and already live on agents.

**The legacy entity path goes.** After the migration below, an entry either has
agents or provides no conversation entity at all. A hub with no agents is a
connection nobody is using yet, which is a coherent state and not an error.

**A migration converts the legacy users rather than stranding them.** On entry
setup, if an entry has agent-shaped `options` and **no** conversation
subentries, create a subentry from those options and clear them. Their single
agent keeps working, now as a real agent, and their existing entity is
preserved — see §4, which is the delicate part.

**An entry that has both** — options and subentries, like the user's — keeps its
options untouched in storage but stops presenting them. Clearing them would be
tidier and is tempting; it is also the one irreversible act in this change, for
data that costs nothing to leave alone. The migration logs once that it found
and ignored them.

## 4. The entity id, which is where this can hurt

The legacy entity's unique id derives from the config entry; a subentry's
derives from the subentry. A naive migration therefore **creates a new entity
and orphans the old one**, breaking every automation, script and dashboard card
that names it.

So the migration must move the existing registry entry to the new unique id
rather than letting a second one appear. `entity_registry.async_update_entity`
can change a unique id in place, which keeps the entity id, the name, the area
and every reference to it.

**Verified against the installed Home Assistant rather than assumed.**
`EntityRegistry.async_update_entity` accepts `new_unique_id` and guards against
a collision. The two id shapes are `f"{entry.entry_id}_{subentry_id}"` for an
agent and `f"{entry.entry_id}"` for the legacy entity, so the migration rewrites
the latter into the former and the entity id, friendly name, area and every
reference to it survive untouched.

The migration must still refuse rather than guess: if the rewrite raises — a
collision, a registry entry that is not there — it leaves the entry alone and
logs why, and the legacy path stays for that entry. A silent rename that breaks
someone's automations is far worse than carrying the old code path for another
release.

## 5. The panel

The Settings tab becomes connection settings, and shows the provider's few
switches or an honest "this provider has no connection settings".

The Agents tab gains an explicit empty state per hub: a newly connected provider
has no agents, and under the new model **nothing works until one is created**.
That must be visible, not inferred — "No agents on this provider yet" with the
create action beside it, which the tab already has.

## 6. Testing

- **An entry with options and no subentries** gets exactly one subentry after
  setup, carrying those options, and its conversation entity **keeps the same
  entity id** it had before. This is the migration's whole point and the test
  that matters most.
- **An entry with options and subentries** is left alone: the options stay in
  storage, no subentry is created, and the agent count does not change.
- **An entry with neither** provides no conversation entity and does not error.
- **The options flow** offers connection settings only — a schema-driven check
  that no agent field appears in it, so a field added to `subentry_schema` later
  cannot leak back in.
- **A second setup is idempotent**: restarting does not create another subentry
  or migrate twice.

## 7. Deferred

- Editing a hub's credential from the panel — still needs a reauth flow that
  does not exist.
- Removing `verify_ssl` and `profanity` from the agent schema. They are
  connection settings that currently also appear per agent; consolidating them
  is right but is a separate, smaller change, and doing it in the same release
  as the migration would make a failure harder to attribute.
